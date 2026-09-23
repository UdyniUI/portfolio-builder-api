"""Local résumé text extraction and review-data endpoints."""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import Annotated, Literal, Optional
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.connection import get_db
from app.database.models import ResumeUpload

router = APIRouter(prefix="/resumes", tags=["résumés"])

EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
URL_PATTERN = re.compile(
    r"(?:https?://|www\.)\S+|\b(?:linkedin\.com|github\.com)/\S+", re.IGNORECASE
)

SECTION_HEADINGS = {
    "summary": {"summary", "profile", "professional summary", "about", "objective"},
    "experience": {
        "experience",
        "work experience",
        "professional experience",
        "employment",
        "career history",
    },
    "education": {"education", "academic background", "qualifications"},
    "skills": {
        "skills",
        "technical skills",
        "core competencies",
        "competencies",
        "expertise",
    },
    "projects": {"projects", "selected projects", "personal projects", "portfolio"},
}


class ResumeContact(BaseModel):
    name: Annotated[str, Field(max_length=200)] = ""
    email: Annotated[str, Field(max_length=320)] = ""
    phone: Annotated[str, Field(max_length=80)] = ""
    location: Annotated[str, Field(max_length=200)] = ""
    links: list[Annotated[str, Field(max_length=500)]] = Field(
        default_factory=list, max_length=20
    )


class ResumeSections(BaseModel):
    summary: Annotated[str, Field(max_length=30_000)] = ""
    experience: Annotated[str, Field(max_length=100_000)] = ""
    education: Annotated[str, Field(max_length=30_000)] = ""
    skills: Annotated[str, Field(max_length=30_000)] = ""
    projects: Annotated[str, Field(max_length=60_000)] = ""


class ExtractedResumeData(BaseModel):
    schema_version: Literal[1] = 1
    contact: ResumeContact = Field(default_factory=ResumeContact)
    sections: ResumeSections = Field(default_factory=ResumeSections)
    unclassified_text: Annotated[str, Field(max_length=100_000)] = ""
    raw_text: Annotated[str, Field(max_length=250_000)] = ""
    warnings: list[Annotated[str, Field(max_length=500)]] = Field(
        default_factory=list, max_length=20
    )


class ResumeExtractionResponse(BaseModel):
    id: int
    original_filename: str
    extraction_status: Literal["pending", "processing", "completed", "failed"]
    extracted_data: Optional[ExtractedResumeData] = None
    error: Optional[str] = None


class ExtractionError(Exception):
    """A résumé cannot be converted into reviewable text."""


def _require_local_environment() -> None:
    if get_settings().environment not in {"development", "test"}:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Résumé extraction requires an authenticated user in this environment.",
        )


def _get_upload(db: Session, upload_id: int) -> ResumeUpload:
    upload = db.get(ResumeUpload, upload_id)
    if upload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Résumé upload not found."
        )
    return upload


def _stored_resume_path(upload: ResumeUpload) -> Path:
    prefix = "local://resumes/"
    if not upload.file_url.startswith(prefix):
        raise ExtractionError(
            "This résumé is not stored in the local upload workspace."
        )

    stored_filename = upload.file_url.removeprefix(prefix)
    if not stored_filename or Path(stored_filename).name != stored_filename:
        raise ExtractionError("The stored résumé path is invalid.")

    upload_dir = Path(get_settings().resume_upload_dir).expanduser().resolve()
    path = upload_dir / stored_filename
    if not path.is_file():
        raise ExtractionError("The uploaded résumé file is missing. Upload it again.")
    return path


def _extract_pdf_text(content: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise ExtractionError("Password-protected PDFs are not supported yet.")
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ExtractionError:
        raise
    except (PdfReadError, ValueError, OSError) as exc:
        raise ExtractionError(
            "The PDF could not be read. Export it again and retry."
        ) from exc


def _extract_docx_text(content: bytes) -> str:
    try:
        with ZipFile(BytesIO(content)) as archive:
            document_xml = archive.read("word/document.xml")
    except (BadZipFile, KeyError, OSError) as exc:
        raise ExtractionError(
            "The DOCX document could not be read. Export it again and retry."
        ) from exc

    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as exc:
        raise ExtractionError("The DOCX document contains invalid text data.") from exc

    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = []
    for paragraph in root.iter(f"{namespace}p"):
        text = "".join(
            node.text or "" for node in paragraph.iter(f"{namespace}t")
        ).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def extract_text(path: Path) -> str:
    content = path.read_bytes()
    if path.suffix.lower() == ".pdf":
        text = _extract_pdf_text(content)
    elif path.suffix.lower() == ".docx":
        text = _extract_docx_text(content)
    else:
        raise ExtractionError("Only PDF and DOCX résumés can be extracted.")

    normalized = "\n".join(
        line.strip() for line in text.replace("\x00", "").splitlines() if line.strip()
    )
    if not normalized:
        raise ExtractionError(
            "No selectable text was found. For a scanned PDF, use OCR and upload it again."
        )
    return normalized[:250_000]


def _heading_key(line: str) -> Optional[str]:
    normalized = re.sub(r"[^a-z ]", "", line.lower()).strip()
    for key, headings in SECTION_HEADINGS.items():
        if normalized in headings:
            return key
    return None


def structure_resume_text(raw_text: str) -> ExtractedResumeData:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    email_match = EMAIL_PATTERN.search(raw_text)
    phone_match = PHONE_PATTERN.search(raw_text)
    links = list(
        dict.fromkeys(match.rstrip(".,;)") for match in URL_PATTERN.findall(raw_text))
    )

    first_heading_index = next(
        (index for index, line in enumerate(lines) if _heading_key(line)), len(lines)
    )
    header_lines = lines[:first_heading_index]
    name = next(
        (
            line
            for line in header_lines
            if len(line) <= 200
            and len(line.split()) <= 8
            and not EMAIL_PATTERN.search(line)
            and not PHONE_PATTERN.search(line)
            and not URL_PATTERN.search(line)
        ),
        "",
    )

    buckets: dict[str, list[str]] = {key: [] for key in SECTION_HEADINGS}
    unclassified = []
    active_section: Optional[str] = None
    for line in lines:
        heading = _heading_key(line)
        if heading:
            active_section = heading
            continue
        if (
            line == name
            or EMAIL_PATTERN.fullmatch(line)
            or PHONE_PATTERN.fullmatch(line)
            or URL_PATTERN.fullmatch(line)
        ):
            continue
        if active_section:
            buckets[active_section].append(line)
        else:
            unclassified.append(line)

    if not buckets["summary"] and unclassified:
        buckets["summary"] = unclassified
        unclassified = []

    required_sections = ("summary", "experience", "education", "skills")
    missing_sections = [key for key in required_sections if not buckets[key]]
    warnings = []
    if missing_sections:
        warnings.append(
            f"No clear {', '.join(missing_sections)} section was detected. Add or correct it during review."
        )
    if not email_match:
        warnings.append("No email address was detected.")

    return ExtractedResumeData(
        contact=ResumeContact(
            name=name,
            email=email_match.group(0) if email_match else "",
            phone=phone_match.group(0).strip() if phone_match else "",
            links=links,
        ),
        sections=ResumeSections(
            **{key: "\n".join(values) for key, values in buckets.items()}
        ),
        unclassified_text="\n".join(unclassified),
        raw_text=raw_text,
        warnings=warnings,
    )


def _response(upload: ResumeUpload) -> ResumeExtractionResponse:
    payload = upload.extracted_data or {}
    if upload.extraction_status == "completed":
        return ResumeExtractionResponse(
            id=upload.id,
            original_filename=upload.original_filename or "résumé",
            extraction_status="completed",
            extracted_data=ExtractedResumeData.model_validate(payload),
        )
    return ResumeExtractionResponse(
        id=upload.id,
        original_filename=upload.original_filename or "résumé",
        extraction_status=upload.extraction_status,
        error=payload.get("error") if isinstance(payload, dict) else None,
    )


@router.post("/{upload_id}/extract", response_model=ResumeExtractionResponse)
def extract_resume(
    upload_id: int, db: Session = Depends(get_db)
) -> ResumeExtractionResponse:
    """Extract and structure a locally uploaded résumé. Safe to retry."""

    _require_local_environment()
    upload = _get_upload(db, upload_id)
    if upload.extraction_status == "completed" and upload.extracted_data:
        return _response(upload)

    try:
        upload.extraction_status = "processing"
        upload.extracted_data = None
        db.commit()

        raw_text = extract_text(_stored_resume_path(upload))
        structured = structure_resume_text(raw_text)
        upload.extracted_data = structured.model_dump()
        upload.extraction_status = "completed"
        db.commit()
        db.refresh(upload)
    except (ExtractionError, OSError) as exc:
        db.rollback()
        upload = _get_upload(db, upload_id)
        upload.extraction_status = "failed"
        upload.extracted_data = {"error": str(exc)}
        db.commit()
        db.refresh(upload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The extraction result could not be stored. Please try again.",
        ) from exc

    return _response(upload)


@router.get("/{upload_id}", response_model=ResumeExtractionResponse)
def get_resume(
    upload_id: int, db: Session = Depends(get_db)
) -> ResumeExtractionResponse:
    _require_local_environment()
    return _response(_get_upload(db, upload_id))


@router.put("/{upload_id}/extracted-data", response_model=ResumeExtractionResponse)
def update_extracted_resume(
    upload_id: int,
    data: ExtractedResumeData,
    db: Session = Depends(get_db),
) -> ResumeExtractionResponse:
    """Persist user-reviewed corrections without changing the source file."""

    _require_local_environment()
    upload = _get_upload(db, upload_id)
    if upload.extraction_status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Complete résumé extraction before saving corrections.",
        )
    try:
        upload.extracted_data = data.model_dump()
        db.commit()
        db.refresh(upload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The résumé corrections could not be saved. Please try again.",
        ) from exc
    return _response(upload)

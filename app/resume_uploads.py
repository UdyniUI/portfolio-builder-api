"""Local-development résumé upload API."""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Optional
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.connection import get_db
from app.database.models import ResumeUpload, User

router = APIRouter(tags=["résumés"])


@dataclass(frozen=True)
class ResumeFormat:
    extension: str
    content_types: frozenset[str]


RESUME_FORMATS = {
    ".pdf": ResumeFormat(
        extension=".pdf",
        content_types=frozenset({"application/pdf", "application/octet-stream"}),
    ),
    ".docx": ResumeFormat(
        extension=".docx",
        content_types=frozenset(
            {
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/zip",
                "application/octet-stream",
            }
        ),
    ),
}


class ResumeUploadResponse(BaseModel):
    id: int
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    extraction_status: str
    created_at: datetime


def _safe_original_filename(filename: Optional[str]) -> str:
    normalized = (filename or "").replace("\\", "/")
    safe_name = normalized.rsplit("/", 1)[-1].strip()
    if not safe_name or safe_name in {".", ".."}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded résumé must have a filename.",
        )
    if len(safe_name) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The résumé filename must be 255 characters or fewer.",
        )
    return safe_name


def _validate_resume_format(
    filename: str, content_type: Optional[str], content: bytes
) -> ResumeFormat:
    extension = Path(filename).suffix.lower()
    resume_format = RESUME_FORMATS.get(extension)
    if resume_format is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Choose a PDF or DOCX résumé.",
        )

    normalized_content_type = (content_type or "application/octet-stream").lower()
    if normalized_content_type not in resume_format.content_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"The file type does not match the {extension[1:].upper()} filename.",
        )

    if extension == ".pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The selected file is not a valid PDF.",
        )

    if extension == ".docx":
        try:
            with ZipFile(BytesIO(content)) as archive:
                names = set(archive.namelist())
        except BadZipFile as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The selected file is not a valid DOCX document.",
            ) from exc
        required_parts = {"[Content_Types].xml", "word/document.xml"}
        if not required_parts.issubset(names):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The selected file is not a valid DOCX document.",
            )

    return resume_format


def _read_bounded(file: BinaryIO, max_bytes: int) -> bytes:
    content = file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"The résumé is larger than {max_bytes // (1024 * 1024)} MB.",
        )
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The selected résumé is empty.",
        )
    return content


def _local_user(db: Session) -> User:
    settings = get_settings()
    user = (
        db.query(User)
        .filter(
            or_(
                User.auth0_id == settings.local_auth_user_id,
                User.email == settings.local_auth_email,
            )
        )
        .first()
    )
    if user is not None:
        return user

    user = User(
        auth0_id=settings.local_auth_user_id,
        email=settings.local_auth_email,
        first_name="Local",
        last_name="Developer",
    )
    db.add(user)
    db.flush()
    return user


@router.post(
    "/upload",
    response_model=ResumeUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_resume(
    file: UploadFile = File(..., description="A PDF or DOCX résumé up to 10 MB."),
    db: Session = Depends(get_db),
) -> ResumeUploadResponse:
    """Persist a résumé locally and record its metadata in PostgreSQL."""

    settings = get_settings()
    if settings.environment not in {"development", "test"}:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Résumé upload requires an authenticated user in this environment.",
        )

    original_filename = _safe_original_filename(file.filename)
    content = _read_bounded(file.file, settings.max_resume_size_bytes)
    resume_format = _validate_resume_format(
        original_filename, file.content_type, content
    )

    upload_dir = Path(settings.resume_upload_dir).expanduser().resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_filename = f"{uuid4().hex}{resume_format.extension}"
    destination = upload_dir / stored_filename
    temporary_destination = upload_dir / f".{stored_filename}.part"

    try:
        with temporary_destination.open("xb") as destination_file:
            destination_file.write(content)
        temporary_destination.replace(destination)

        user = _local_user(db)
        upload = ResumeUpload(
            user_id=user.id,
            file_url=f"local://resumes/{stored_filename}",
            original_filename=original_filename,
            extraction_status="pending",
        )
        db.add(upload)
        db.commit()
        db.refresh(upload)
    except SQLAlchemyError as exc:
        db.rollback()
        destination.unlink(missing_ok=True)
        temporary_destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The résumé could not be recorded. Please try again.",
        ) from exc
    except OSError as exc:
        db.rollback()
        destination.unlink(missing_ok=True)
        temporary_destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The résumé could not be stored. Please try again.",
        ) from exc

    return ResumeUploadResponse(
        id=upload.id,
        original_filename=original_filename,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        sha256=sha256(content).hexdigest(),
        extraction_status=upload.extraction_status,
        created_at=upload.created_at,
    )

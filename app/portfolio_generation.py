"""Generate a local, unpublished portfolio draft from reviewed resume data."""

from __future__ import annotations

import base64
import copy
import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, Optional

import httpx
import yaml
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.connection import get_db
from app.database.models import (
    DesignSystem,
    Portfolio,
    PortfolioData,
    ResumeUpload,
    WireframeTemplate,
)
from app.resume_extraction import ExtractedResumeData

router = APIRouter(tags=["portfolios"])

DEFAULT_DESIGN_SLUG = "night-shift"
DEFAULT_TEMPLATE_SLUG = "executive-brief"

EXPERIENCE_DATE_PATTERN = re.compile(
    r"^(?:(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\s+)?(?:19|20)\d{2}\s*(?:[-–—]|to)\s*"
    r"(?:(?:(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\s+)?(?:19|20)\d{2}|present|current)$",
    re.IGNORECASE,
)
EXPERIENCE_PREFIXES = {
    "role": ("role:", "title:"),
    "company": ("company:", "organization:", "organisation:"),
    "dates": ("dates:", "date:"),
    "summary": ("summary:", "overview:", "scope:"),
    "outcomes": ("impact:", "outcome:", "outcomes:", "result:", "results:"),
    "skills": ("skills:", "tools:", "technologies:"),
}


class DraftDesign(BaseModel):
    id: int
    name: str
    slug: str
    description: Optional[str]
    tokens: dict[str, Any]
    is_custom: bool
    base_design_system_id: Optional[int] = None
    token_overrides: dict[str, Any] = Field(default_factory=dict)


class DraftTemplate(BaseModel):
    id: int
    name: str
    slug: str
    description: Optional[str]
    sections: list[dict[str, Any]]
    layout: Optional[dict[str, Any]] = None
    is_custom: bool = False


class DraftSection(BaseModel):
    key: str
    content: dict[str, Any]
    order_index: int


class ContentGap(BaseModel):
    id: str
    field_id: str
    section_key: str
    title: str
    prompt: str
    severity: Literal["blocking", "recommended"]
    action: Literal["edit", "select"] = "edit"


class ContentReadiness(BaseModel):
    score: int
    label: str
    ready_checks: int
    total_checks: int
    gaps: list[ContentGap]


class BuilderState(BaseModel):
    revision: int
    configuration_status: Literal["editing", "configured"]
    configured_at: Optional[str] = None


class PortfolioDraftResponse(BaseModel):
    id: int
    resume_upload_id: int
    title: str
    slug: str
    status: str
    design_system: DraftDesign
    template: DraftTemplate
    sections: list[DraftSection]
    content_model: dict[str, Any]
    readiness: ContentReadiness
    builder: BuilderState


class PortfolioOptionsResponse(BaseModel):
    design_systems: list[DraftDesign]
    templates: list[DraftTemplate]


class AppearanceInput(BaseModel):
    design_system_id: Optional[int] = None
    template_id: Optional[int] = None


class DesignMarkdownInput(BaseModel):
    markdown: str = Field(min_length=1, max_length=100_000)


class DesignInterpretation(BaseModel):
    name: str
    description: str
    tokens: dict[str, Any]
    sources: dict[str, dict[str, str]]
    detected: list[str]
    warnings: list[str]


class DesignImportResponse(BaseModel):
    draft: PortfolioDraftResponse
    interpretation: DesignInterpretation


class DesignEditorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=88)
    colors: dict[str, str] = Field(default_factory=dict)
    typography: dict[str, str] = Field(default_factory=dict)


class DesignEditResponse(BaseModel):
    draft: PortfolioDraftResponse
    warnings: list[str]


SectionKey = Literal[
    "hero", "about", "skills", "experience", "education", "projects", "contact"
]


class ContentFieldEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_id: str = Field(min_length=1, max_length=120)
    value: Any
    hidden: bool = False


class PortfolioContentEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: list[ContentFieldEdit] = Field(default_factory=list, max_length=20)
    featured_role_ids: Optional[list[str]] = Field(default=None, max_length=12)
    section_visibility: Optional[dict[SectionKey, bool]] = None


class PortfolioCommitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


class PortfolioCommitResponse(BaseModel):
    draft: PortfolioDraftResponse
    snapshot: dict[str, Any]


class WireframeSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: SectionKey
    label: str = Field(min_length=1, max_length=60)
    width: Literal["narrow", "content", "wide", "full"]
    alignment: Literal["left", "center"]
    emphasis: Literal["primary", "standard", "quiet"]
    group: str = Field(max_length=60)
    slots: list[str] = Field(default_factory=list, max_length=12)
    required_slots: list[str] = Field(default_factory=list, max_length=12)
    min_items: int = Field(default=0, ge=0, le=12)
    max_items: int = Field(default=1, ge=1, le=12)
    item_limits: dict[str, int] = Field(default_factory=dict)
    overflow: Literal["rank", "condense", "show-all"] = "show-all"
    fallback: Literal["collapse", "raw-text", "show-available"] = "collapse"


class WireframeViewport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_width: Literal["narrow", "standard", "wide"]
    columns: Literal[1, 2]
    navigation: Literal["inline", "compact", "none"]


class WireframeAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0, le=1)
    sections: list[WireframeSection] = Field(min_length=3, max_length=7)
    desktop: WireframeViewport
    mobile: WireframeViewport
    detected: list[str] = Field(max_length=12)
    warnings: list[str] = Field(max_length=12)
    unsupported: list[str] = Field(max_length=12)


class WireframeInterpretation(WireframeAnalysis):
    desktop_filename: str = ""
    mobile_filename: str = ""


class WireframeApproval(BaseModel):
    interpretation: WireframeInterpretation


class WireframeImportResponse(BaseModel):
    draft: PortfolioDraftResponse
    interpretation: WireframeInterpretation


def _require_local_environment() -> None:
    if get_settings().environment not in {"development", "test"}:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Portfolio generation requires an authenticated user in this environment.",
        )


def _slug_base(name: str, filename: str) -> str:
    source = name.strip() or Path(filename).stem
    slug = re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-")
    return f"{slug or 'portfolio'}-portfolio"


def _available_slug(db: Session, base: str) -> str:
    candidate = base
    suffix = 2
    while db.query(Portfolio.id).filter(Portfolio.slug == candidate).first():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _split_skills(value: str) -> list[str]:
    return [
        item.strip(" -•\t")
        for item in re.split(r"[,;\n]+", value)
        if item.strip(" -•\t")
    ]


def _role_and_company(line: str) -> Optional[tuple[str, str, str]]:
    if (
        line.lstrip().startswith(("-", "•", "*"))
        or len(line) > 180
        or EXPERIENCE_DATE_PATTERN.fullmatch(line)
    ):
        return None
    if " | " in line:
        parts = [part.strip() for part in line.split(" | ")]
        if len(parts) == 3 and EXPERIENCE_DATE_PATTERN.fullmatch(parts[2]):
            role, company, dates = parts
            if role and company:
                return role, company, dates
        if len(parts) == 2:
            role, company = parts
            if role and company and not EXPERIENCE_DATE_PATTERN.fullmatch(company):
                return role, company, ""
        return None

    for separator in (" — ", " – ", " at "):
        if separator not in line:
            continue
        role, company = (part.strip() for part in line.split(separator, 1))
        if (
            role
            and company
            and not EXPERIENCE_DATE_PATTERN.fullmatch(role)
            and not EXPERIENCE_DATE_PATTERN.fullmatch(company)
        ):
            return role, company, ""
    return None


def _prefixed_value(line: str, prefixes: tuple[str, ...]) -> Optional[str]:
    lowered = line.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def _experience_items(value: str) -> list[dict[str, Any]]:
    """Turn reviewed role lines into honest, structured case studies.

    A role starts with ``Role — Company`` (also supports an en dash, pipe, or
    ``at``). Everything else remains visible as a responsibility unless the
    user explicitly labels it as an overview, outcome, or skills line.
    """

    items: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None
    pending_company = ""

    def empty_role() -> dict[str, Any]:
        return {
            "role": "",
            "company": "",
            "dates": "",
            "summary": "",
            "highlights": [],
            "outcomes": [],
            "skills": [],
        }

    for source_line in value.splitlines():
        line = source_line.strip()
        if not line:
            continue

        heading = _role_and_company(line)
        if heading:
            if current and current["role"]:
                items.append(current)
            role, company, dates = heading
            current = empty_role()
            current["role"] = role
            current["company"] = company
            current["dates"] = dates
            continue

        role = _prefixed_value(line, EXPERIENCE_PREFIXES["role"])
        if role is not None:
            if current and current["role"]:
                items.append(current)
            current = empty_role()
            current["role"] = role
            current["company"] = pending_company
            pending_company = ""
            continue

        company = _prefixed_value(line, EXPERIENCE_PREFIXES["company"])
        if company is not None:
            if current is None:
                pending_company = company
            else:
                current["company"] = company
            continue

        if current is None:
            continue

        dates = _prefixed_value(line, EXPERIENCE_PREFIXES["dates"])
        if dates is not None:
            current["dates"] = dates
            continue

        summary = _prefixed_value(line, EXPERIENCE_PREFIXES["summary"])
        if summary is not None:
            current["summary"] = summary
            continue

        outcome = _prefixed_value(line, EXPERIENCE_PREFIXES["outcomes"])
        if outcome is not None:
            if outcome:
                current["outcomes"].append(outcome)
            continue

        skills = _prefixed_value(line, EXPERIENCE_PREFIXES["skills"])
        if skills is not None:
            current["skills"].extend(_split_skills(skills))
            continue

        if not current["dates"] and EXPERIENCE_DATE_PATTERN.fullmatch(line):
            current["dates"] = line
            continue

        highlight = line.lstrip("-•* \t")
        if highlight:
            current["highlights"].append(highlight)

    if current and current["role"]:
        items.append(current)
    return items


def _resolved_design_tokens(design: DesignSystem) -> dict[str, Any]:
    if design.base_design_system_id and design.base_design_system:
        base = _resolved_design_tokens(design.base_design_system)
    else:
        base = design.tokens or {}
    resolved = {
        "colors": dict(base.get("colors", {})),
        "typography": dict(base.get("typography", {})),
    }
    for group in ("colors", "typography"):
        overrides = (design.token_overrides or {}).get(group, {})
        if isinstance(overrides, dict):
            resolved[group].update(overrides)
    return resolved


def _design_type(design: DesignSystem) -> DraftDesign:
    return DraftDesign(
        id=design.id,
        name=design.name,
        slug=design.slug,
        description=design.description,
        tokens=_resolved_design_tokens(design),
        is_custom=not design.is_public,
        base_design_system_id=design.base_design_system_id,
        token_overrides=design.token_overrides or {},
    )


def _template_type(template: WireframeTemplate) -> DraftTemplate:
    return DraftTemplate(
        id=template.id,
        name=template.name,
        slug=template.slug,
        description=template.description,
        sections=template.sections,
        layout=template.layout,
        is_custom=not template.is_public,
    )


def _wireframe_file(file: UploadFile, max_bytes: int) -> tuple[str, str, bytes]:
    filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not filename or len(filename) > 255:
        raise HTTPException(
            status_code=400, detail="The wireframe must have a valid filename."
        )
    extension = Path(filename).suffix.lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".pdf": "application/pdf",
    }
    media_type = media_types.get(extension)
    if media_type is None:
        raise HTTPException(
            status_code=415, detail="Choose a PNG, JPG, or single-page PDF wireframe."
        )
    content = file.file.read(max_bytes + 1)
    if not content:
        raise HTTPException(status_code=400, detail=f"{filename} is empty.")
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"{filename} is larger than {max_bytes // (1024 * 1024)} MB.",
        )
    valid_signature = (
        (extension == ".png" and content.startswith(b"\x89PNG\r\n\x1a\n"))
        or (extension in {".jpg", ".jpeg"} and content.startswith(b"\xff\xd8\xff"))
        or (extension == ".pdf" and content.startswith(b"%PDF-"))
    )
    if not valid_signature:
        raise HTTPException(
            status_code=400, detail=f"{filename} does not match its file type."
        )
    if extension == ".pdf":
        try:
            if len(PdfReader(BytesIO(content)).pages) != 1:
                raise HTTPException(
                    status_code=422,
                    detail="Wireframe PDFs must contain exactly one page.",
                )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"{filename} is not a readable PDF."
            ) from exc
    return filename, media_type, content


def _openai_file_part(filename: str, media_type: str, content: bytes) -> dict[str, str]:
    encoded = base64.b64encode(content).decode("ascii")
    if media_type == "application/pdf":
        return {
            "type": "input_file",
            "filename": filename,
            "file_data": f"data:{media_type};base64,{encoded}",
        }
    return {
        "type": "input_image",
        "detail": "high",
        "image_url": f"data:{media_type};base64,{encoded}",
    }


def _structured_output_schema() -> dict[str, Any]:
    """Keep the Pydantic shape while removing validation-only schema keywords."""

    unsupported = {
        "default",
        "maxItems",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "title",
    }

    def normalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: normalize(item)
                for key, item in value.items()
                if key not in unsupported
            }
        if isinstance(value, list):
            return [normalize(item) for item in value]
        return value

    return normalize(WireframeAnalysis.model_json_schema())


def _interpret_wireframe_with_openai(
    desktop: tuple[str, str, bytes], mobile: Optional[tuple[str, str, bytes]]
) -> WireframeAnalysis:
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=503,
            detail="Wireframe interpretation needs OPENAI_API_KEY in the API environment.",
        )
    prompt = (
        "Interpret these portfolio wireframes as layout structure only. Do not extract colors, fonts, images, "
        "copy, or visual styling. Map only to these supported sections: hero, about, experience (role projects), "
        "skills, education, projects (optional additional work), and contact. Experience is the primary project "
        "section; do not invent a separate projects section unless it is clearly present. Return each included "
        "section exactly once in visual order. The desktop file is first; an optional mobile reference follows. "
        "When mobile is absent, derive a sensible stacked mobile structure. Put anything outside the constrained "
        "system in unsupported and uncertainty in warnings. Group names are short labels or an empty string."
    )
    content: list[dict[str, str]] = [{"type": "input_text", "text": prompt}]
    content.append(_openai_file_part(*desktop))
    if mobile:
        content.append(_openai_file_part(*mobile))
    payload = {
        "model": settings.openai_wireframe_model,
        "store": False,
        "input": [{"role": "user", "content": content}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "portfolio_wireframe",
                "strict": True,
                "schema": _structured_output_schema(),
            }
        },
    }
    try:
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json=payload,
            timeout=90.0,
        )
        response.raise_for_status()
        body = response.json()
        output_text = next(
            part["text"]
            for item in body.get("output", [])
            if item.get("type") == "message"
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )
        return WireframeAnalysis.model_validate_json(output_text)
    except (httpx.HTTPError, KeyError, StopIteration, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail="The wireframe could not be interpreted right now. Check the OpenAI API configuration and try again.",
        ) from exc


def _validate_wireframe_sections(sections: list[WireframeSection]) -> None:
    keys = [section.key for section in sections]
    if len(keys) != len(set(keys)):
        raise HTTPException(
            status_code=422, detail="Each portfolio section can appear only once."
        )
    required = {"hero", "experience", "contact"}
    if not required.issubset(keys):
        raise HTTPException(
            status_code=422,
            detail="The approved wireframe must include hero, role projects, and contact.",
        )
    if keys[0] != "hero" or keys[-1] != "contact":
        raise HTTPException(
            status_code=422,
            detail="Place the hero first and contact last before approving the wireframe.",
        )


def _has_content(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_has_content(item) for item in value)
    return value is not None


def _content_field(
    field_id: str,
    label: str,
    section_key: str,
    value: Any,
    source_ref: str,
    *,
    provenance: Literal["extracted", "derived"] = "extracted",
    importance: Literal["required", "recommended", "optional"] = "optional",
    confidence: float = 1.0,
) -> dict[str, Any]:
    ready = _has_content(value)
    return {
        "id": field_id,
        "label": label,
        "section_key": section_key,
        "value": value,
        "provenance": provenance,
        "source_refs": [source_ref],
        "confidence": confidence,
        "approval_state": "approved" if provenance == "extracted" else "pending",
        "importance": importance,
        "status": (
            "ready"
            if ready
            else "blocking_gap"
            if importance == "required"
            else "optional_gap"
        ),
    }


def _canonical_content(data: ExtractedResumeData) -> dict[str, Any]:
    contact = data.contact
    sections = data.sections
    roles = _experience_items(sections.experience)
    fields = {
        "identity.name": _content_field(
            "identity.name",
            "Name",
            "hero",
            contact.name,
            "resume.contact.name",
            importance="required",
        ),
        "identity.headline": _content_field(
            "identity.headline",
            "Portfolio headline",
            "hero",
            sections.summary.splitlines()[0] if sections.summary else "",
            "resume.sections.summary",
            provenance="derived",
            importance="required",
            confidence=0.95,
        ),
        "identity.location": _content_field(
            "identity.location",
            "Location",
            "hero",
            contact.location,
            "resume.contact.location",
        ),
        "about.body": _content_field(
            "about.body",
            "Positioning statement",
            "about",
            sections.summary,
            "resume.sections.summary",
            provenance="derived",
            importance="recommended",
            confidence=0.95,
        ),
        "capabilities.items": _content_field(
            "capabilities.items",
            "Capabilities",
            "skills",
            _split_skills(sections.skills),
            "resume.sections.skills",
            importance="recommended",
        ),
        "experience.raw": _content_field(
            "experience.raw",
            "Experience fallback",
            "experience",
            sections.experience,
            "resume.sections.experience",
        ),
        "education.body": _content_field(
            "education.body",
            "Education",
            "education",
            sections.education,
            "resume.sections.education",
        ),
        "projects.body": _content_field(
            "projects.body",
            "Additional work",
            "projects",
            sections.projects,
            "resume.sections.projects",
        ),
        "contact.email": _content_field(
            "contact.email",
            "Email",
            "contact",
            contact.email,
            "resume.contact.email",
            importance="recommended",
        ),
        "contact.phone": _content_field(
            "contact.phone",
            "Phone",
            "contact",
            contact.phone,
            "resume.contact.phone",
        ),
        "contact.location": _content_field(
            "contact.location",
            "Contact location",
            "contact",
            contact.location,
            "resume.contact.location",
        ),
        "contact.links": _content_field(
            "contact.links",
            "Public links",
            "contact",
            contact.links,
            "resume.contact.links",
            importance="recommended",
        ),
    }
    role_stories = []
    for index, role in enumerate(roles, start=1):
        role_id = f"role-{index}"
        role_stories.append(
            {
                "id": role_id,
                "fields": {
                    key: _content_field(
                        f"{role_id}.{key}",
                        label,
                        "experience",
                        role[key],
                        f"resume.sections.experience.{index - 1}.{key}",
                        importance=importance,
                    )
                    for key, label, importance in (
                        ("role", "Role title", "required"),
                        ("company", "Company", "required"),
                        ("dates", "Dates", "recommended"),
                        ("summary", "Context", "recommended"),
                        ("highlights", "Contributions", "required"),
                        ("outcomes", "Outcomes", "recommended"),
                        ("skills", "Role capabilities", "optional"),
                    )
                },
            }
        )
    return {
        "version": 1,
        "fields": fields,
        "role_stories": role_stories,
        "featured_role_ids": [role["id"] for role in role_stories],
        "selection_approved": len(role_stories) <= 2,
        "section_visibility": {
            key: True
            for key in (
                "hero",
                "about",
                "skills",
                "experience",
                "education",
                "projects",
                "contact",
            )
        },
    }


def _merge_user_content(
    generated: dict[str, Any], existing: Optional[dict[str, Any]]
) -> dict[str, Any]:
    if not existing or existing.get("version") != 1:
        return generated
    merged = copy.deepcopy(generated)
    old_fields = existing.get("fields", {})
    for field_id, current in merged["fields"].items():
        previous = old_fields.get(field_id)
        if isinstance(previous, dict) and (
            previous.get("provenance") == "user-authored"
            or previous.get("status") == "hidden"
        ):
            merged["fields"][field_id] = previous
    old_roles = {
        role.get("id"): role
        for role in existing.get("role_stories", [])
        if isinstance(role, dict)
    }
    for role in merged["role_stories"]:
        previous_role = old_roles.get(role["id"])
        if not previous_role:
            continue
        for key, current in role["fields"].items():
            previous = previous_role.get("fields", {}).get(key)
            if isinstance(previous, dict) and (
                previous.get("provenance") == "user-authored"
                or previous.get("status") == "hidden"
            ):
                role["fields"][key] = previous
    valid_role_ids = {role["id"] for role in merged["role_stories"]}
    featured = [
        role_id
        for role_id in existing.get("featured_role_ids", [])
        if role_id in valid_role_ids
    ]
    if featured:
        merged["featured_role_ids"] = featured
        merged["selection_approved"] = bool(existing.get("selection_approved"))
    visibility = existing.get("section_visibility")
    if isinstance(visibility, dict):
        merged["section_visibility"].update(
            {key: value for key, value in visibility.items() if isinstance(value, bool)}
        )
    return merged


def _field_value(content: dict[str, Any], field_id: str, default: Any = "") -> Any:
    field = content.get("fields", {}).get(field_id)
    if not isinstance(field, dict) or field.get("status") == "hidden":
        return default
    return field.get("value", default)


def _role_value(role: dict[str, Any], key: str, default: Any = "") -> Any:
    field = role.get("fields", {}).get(key)
    if not isinstance(field, dict) or field.get("status") == "hidden":
        return default
    return field.get("value", default)


def _materialized_sections(content: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    featured = content.get("featured_role_ids", [])
    priority = {role_id: index for index, role_id in enumerate(featured)}
    role_stories = list(content.get("role_stories", []))
    role_stories.sort(
        key=lambda role: (
            priority.get(role.get("id"), len(priority)),
            next(
                (
                    index
                    for index, candidate in enumerate(content.get("role_stories", []))
                    if candidate.get("id") == role.get("id")
                ),
                len(role_stories),
            ),
        )
    )
    roles = [
        {
            "id": role.get("id", ""),
            "role": _role_value(role, "role"),
            "company": _role_value(role, "company"),
            "dates": _role_value(role, "dates"),
            "summary": _role_value(role, "summary"),
            "highlights": _role_value(role, "highlights", []),
            "outcomes": _role_value(role, "outcomes", []),
            "skills": _role_value(role, "skills", []),
        }
        for role in role_stories
    ]
    links = _field_value(content, "contact.links", [])
    return [
        (
            "hero",
            {
                "name": _field_value(content, "identity.name"),
                "headline": _field_value(content, "identity.headline"),
                "location": _field_value(content, "identity.location"),
                "links": links,
            },
        ),
        ("about", {"body": _field_value(content, "about.body")}),
        ("skills", {"items": _field_value(content, "capabilities.items", [])}),
        (
            "experience",
            {
                "body": _field_value(content, "experience.raw"),
                "items": roles,
            },
        ),
        ("education", {"body": _field_value(content, "education.body")}),
        ("projects", {"body": _field_value(content, "projects.body")}),
        (
            "contact",
            {
                "email": _field_value(content, "contact.email"),
                "phone": _field_value(content, "contact.phone"),
                "location": _field_value(content, "contact.location"),
                "links": links,
            },
        ),
    ]


def _sync_portfolio_sections(db: Session, portfolio: Portfolio) -> None:
    existing = {section.section_key: section for section in portfolio.portfolio_data}
    for index, (key, section_content) in enumerate(
        _materialized_sections(portfolio.content_model or {})
    ):
        section = existing.get(key)
        if section is None:
            db.add(
                PortfolioData(
                    portfolio_id=portfolio.id,
                    section_key=key,
                    content=section_content,
                    order_index=index,
                )
            )
        else:
            section.content = section_content
            section.order_index = index


def _content_field_by_id(
    content: dict[str, Any], field_id: str
) -> Optional[dict[str, Any]]:
    field = content.get("fields", {}).get(field_id)
    if isinstance(field, dict):
        return field
    for role in content.get("role_stories", []):
        if not isinstance(role, dict):
            continue
        for candidate in role.get("fields", {}).values():
            if isinstance(candidate, dict) and candidate.get("id") == field_id:
                return candidate
    return None


def _content_readiness(
    content: dict[str, Any], template: WireframeTemplate
) -> ContentReadiness:
    section_contracts = {
        item.get("key"): item
        for item in (template.sections or [])
        if isinstance(item, dict)
    }
    checks: list[bool] = []
    gaps: list[ContentGap] = []

    def check_field(
        field_id: str,
        title: str,
        prompt: str,
        *,
        blocking: bool = False,
    ) -> None:
        field = _content_field_by_id(content, field_id)
        ready = bool(
            field
            and field.get("status") in {"ready", "hidden"}
            and (field.get("status") == "hidden" or _has_content(field.get("value")))
        )
        checks.append(ready)
        if not ready:
            gaps.append(
                ContentGap(
                    id=f"gap-{field_id}",
                    field_id=field_id,
                    section_key=field.get("section_key", "hero") if field else "hero",
                    title=title,
                    prompt=prompt,
                    severity="blocking" if blocking else "recommended",
                )
            )

    if "hero" in section_contracts:
        check_field(
            "identity.name",
            "Add the portfolio name",
            "This wireframe needs a clear identity in its opening section.",
            blocking=True,
        )
        check_field(
            "identity.headline",
            "Strengthen the opening headline",
            "Write one evidence-backed sentence that explains the work you want to be hired for.",
            blocking=True,
        )
    if "about" in section_contracts:
        check_field(
            "about.body",
            "Clarify your positioning",
            "Use the positioning section to connect your experience into a concise professional story.",
        )
    if "skills" in section_contracts:
        check_field(
            "capabilities.items",
            "Add supported capabilities",
            "Choose capabilities that are explicitly supported by your résumé or your own input.",
        )

    roles = content.get("role_stories", [])
    experience_contract = section_contracts.get("experience")
    if experience_contract:
        has_roles = any(_has_content(_role_value(role, "role")) for role in roles)
        checks.append(has_roles)
        if not has_roles:
            gaps.append(
                ContentGap(
                    id="gap-experience-roles",
                    field_id="experience.raw",
                    section_key="experience",
                    title="Add one role story",
                    prompt="Structure one verified role with its company and contribution before using this wireframe.",
                    severity="blocking",
                )
            )
        for role in roles[: min(3, experience_contract.get("max_items", 3))]:
            role_name = _role_value(role, "role") or "This role"
            outcome_id = f"{role.get('id')}.outcomes"
            outcome_field = _content_field_by_id(content, outcome_id)
            has_outcome = bool(
                outcome_field and _has_content(outcome_field.get("value"))
            )
            checks.append(has_outcome)
            if not has_outcome:
                gaps.append(
                    ContentGap(
                        id=f"gap-{outcome_id}",
                        field_id=outcome_id,
                        section_key="experience",
                        title=f"Add an outcome for {role_name}",
                        prompt="What changed because of your work? Add only a result you can support.",
                        severity="recommended",
                    )
                )
        max_items = experience_contract.get("max_items")
        if isinstance(max_items, int) and len(roles) > max_items:
            featured = content.get("featured_role_ids", [])
            approved = bool(content.get("selection_approved")) and (
                0 < len(featured) <= max_items
            )
            checks.append(approved)
            if not approved:
                gaps.append(
                    ContentGap(
                        id="gap-featured-roles",
                        field_id="experience.featured",
                        section_key="experience",
                        title=f"Choose {max_items} featured roles",
                        prompt=f"This wireframe shows {max_items} of {len(roles)} roles. Choose the work that best supports your direction.",
                        severity="recommended",
                        action="select",
                    )
                )
    if "contact" in section_contracts:
        check_field(
            "contact.email",
            "Add a contact route",
            "Add an email address or intentionally hide the contact section.",
        )
        check_field(
            "contact.links",
            "Add a public work link",
            "Add a portfolio, LinkedIn, GitHub, or other link you want visitors to use.",
        )

    ready_checks = sum(checks)
    total_checks = max(1, len(checks))
    score = round(100 * ready_checks / total_checks)
    blocking_gaps = [gap for gap in gaps if gap.severity == "blocking"]
    label = (
        "Needs attention"
        if blocking_gaps
        else "Ready"
        if score >= 85
        else "Strong start"
    )
    return ContentReadiness(
        score=score,
        label=label,
        ready_checks=ready_checks,
        total_checks=total_checks,
        gaps=sorted(gaps, key=lambda gap: gap.severity != "blocking"),
    )


def _response(db: Session, portfolio: Portfolio) -> PortfolioDraftResponse:
    sections = (
        db.query(PortfolioData)
        .filter(PortfolioData.portfolio_id == portfolio.id)
        .order_by(PortfolioData.order_index, PortfolioData.id)
        .all()
    )
    template_order = {
        section.get("key"): index
        for index, section in enumerate(portfolio.template.sections or [])
        if isinstance(section, dict) and isinstance(section.get("key"), str)
    }
    if template_order and not portfolio.template.is_public:
        sections = [
            section for section in sections if section.section_key in template_order
        ]
    sections.sort(
        key=lambda section: (
            template_order.get(section.section_key, len(template_order)),
            section.order_index,
            section.id,
        )
    )
    content = portfolio.content_model or {}
    if (
        not content
        and portfolio.source_resume
        and portfolio.source_resume.extracted_data
    ):
        content = _canonical_content(
            ExtractedResumeData.model_validate(portfolio.source_resume.extracted_data)
        )
    return PortfolioDraftResponse(
        id=portfolio.id,
        resume_upload_id=portfolio.resume_upload_id,
        title=portfolio.title,
        slug=portfolio.slug,
        status=portfolio.status,
        design_system=_design_type(portfolio.design_system),
        template=_template_type(portfolio.template),
        sections=[
            DraftSection(
                key=item.section_key, content=item.content, order_index=item.order_index
            )
            for item in sections
        ],
        content_model=content,
        readiness=_content_readiness(content, portfolio.template),
        builder=BuilderState(
            revision=portfolio.builder_revision,
            configuration_status=portfolio.configuration_status,
            configured_at=(
                portfolio.configured_at.isoformat() if portfolio.configured_at else None
            ),
        ),
    )


def _portfolio(db: Session, portfolio_id: int) -> Portfolio:
    portfolio = db.get(Portfolio, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio draft not found.")
    return portfolio


def _touch_portfolio(portfolio: Portfolio) -> None:
    """Advance editable state and invalidate an older configured snapshot."""

    portfolio.builder_revision = (portfolio.builder_revision or 0) + 1
    portfolio.configuration_status = "editing"
    portfolio.configuration_snapshot = None
    portfolio.configured_at = None


def _frontmatter(markdown: str) -> dict[str, Any]:
    normalized = markdown.lstrip("\ufeff").replace("\r\n", "\n")
    match = re.match(r"^---\s*\n(.*?)\n---(?:\s*\n|$)", normalized, re.DOTALL)
    if not match:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Add YAML frontmatter between --- lines so PortfolioOS can read the design tokens.",
        )
    try:
        payload = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The DESIGN.md YAML frontmatter is invalid. Check its indentation and quotes.",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The DESIGN.md frontmatter must contain named design properties.",
        )
    return payload


def _value(candidate: Any) -> Optional[str]:
    if isinstance(candidate, str):
        return candidate.strip()
    if isinstance(candidate, dict) and isinstance(candidate.get("value"), str):
        return candidate["value"].strip()
    return None


def _named_value(source: dict[str, Any], names: tuple[str, ...]) -> Optional[str]:
    for name in names:
        if name in source:
            value = _value(source[name])
            if value:
                return value
    return None


def _safe_color(value: Optional[str]) -> Optional[str]:
    if value and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return value.upper()
    return None


def _safe_font(value: Optional[str]) -> Optional[str]:
    if value and len(value) <= 120 and re.fullmatch(r"[A-Za-z0-9 ,'\"_-]+", value):
        return value
    return None


def _relative_luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    lighter, darker = sorted(
        (_relative_luminance(first), _relative_luminance(second)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


EDITABLE_COLOR_ROLES = {
    "primary",
    "accent",
    "ink",
    "paper",
    "surface",
    "quiet",
    "line",
}
EDITABLE_TYPE_ROLES = {"heading", "body", "mono"}


def _design_warnings(tokens: dict[str, Any]) -> list[str]:
    colors = tokens.get("colors", {})
    warnings = []
    for foreground, background, label in (
        ("ink", "paper", "body text on the page"),
        ("accent", "paper", "accent text on the page"),
        ("paper", "primary", "ticker text on the primary color"),
        ("quiet", "surface", "quiet text on section surfaces"),
    ):
        if foreground not in colors or background not in colors:
            continue
        ratio = _contrast(colors[foreground], colors[background])
        if ratio < 4.5:
            warnings.append(
                f"Low contrast ({ratio:.2f}:1) for {label}; use 4.5:1 or higher for small text."
            )
    return warnings


def _validated_overrides(source: DesignEditorInput) -> dict[str, Any]:
    unsupported_colors = sorted(set(source.colors) - EDITABLE_COLOR_ROLES)
    unsupported_type = sorted(set(source.typography) - EDITABLE_TYPE_ROLES)
    if unsupported_colors or unsupported_type:
        unsupported = unsupported_colors + unsupported_type
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported design tokens: {', '.join(unsupported)}.",
        )
    colors = {}
    for role, value in source.colors.items():
        normalized = _safe_color(value)
        if normalized is None:
            raise HTTPException(
                status_code=422,
                detail=f"{role} must be a six-digit hex color.",
            )
        colors[role] = normalized
    typography = {}
    for role, value in source.typography.items():
        normalized = _safe_font(value)
        if normalized is None:
            raise HTTPException(
                status_code=422,
                detail=f"{role} must be a safe local font-family value.",
            )
        typography[role] = normalized
    return {"colors": colors, "typography": typography}


def interpret_design_markdown(
    markdown: str, fallback: dict[str, Any]
) -> DesignInterpretation:
    payload = _frontmatter(markdown)
    metadata = (
        payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    )
    colors = payload.get("colors") if isinstance(payload.get("colors"), dict) else {}
    typography = (
        payload.get("typography") if isinstance(payload.get("typography"), dict) else {}
    )
    fallback_colors = fallback.get("colors", {})
    fallback_type = fallback.get("typography", {})

    color_aliases = {
        "primary": ("primary",),
        "accent": ("accent", "secondary"),
        "ink": ("ink", "text"),
        "paper": ("paper", "background"),
        "surface": ("surface", "background-alt"),
        "quiet": ("quiet", "text-dim", "text-muted"),
        "line": ("line", "surface-border"),
    }
    parsed_colors: dict[str, str] = {}
    ignored_colors = []
    for role, aliases in color_aliases.items():
        raw = _named_value(colors, aliases)
        parsed = _safe_color(raw)
        if raw and not parsed:
            ignored_colors.append(aliases[0])
        if parsed:
            parsed_colors[role] = parsed

    resolved_colors = {
        "primary": parsed_colors.get(
            "primary", fallback_colors.get("primary", "#D8FF5F")
        ),
        "accent": parsed_colors.get("accent", fallback_colors.get("accent", "#7887FF")),
        "ink": parsed_colors.get("ink", fallback_colors.get("ink", "#F5F7F2")),
        "paper": parsed_colors.get("paper", fallback_colors.get("paper", "#090B0F")),
    }
    resolved_colors["surface"] = parsed_colors.get("surface") or (
        resolved_colors["paper"]
        if "paper" in parsed_colors
        else fallback_colors.get("surface", resolved_colors["paper"])
    )
    resolved_colors["quiet"] = parsed_colors.get("quiet") or (
        resolved_colors["ink"]
        if "ink" in parsed_colors
        else fallback_colors.get("quiet", resolved_colors["ink"])
    )
    resolved_colors["line"] = parsed_colors.get("line") or (
        resolved_colors["accent"]
        if "accent" in parsed_colors
        else fallback_colors.get("line", resolved_colors["accent"])
    )
    color_sources = {
        role: "imported" if role in parsed_colors else "retained"
        for role in resolved_colors
    }

    type_aliases = {
        "heading": ("heading", "font-family-heading"),
        "body": ("body", "font-family-body"),
        "mono": ("mono", "font-family-mono"),
    }
    resolved_type: dict[str, str] = {}
    type_sources: dict[str, str] = {}
    for role, aliases in type_aliases.items():
        parsed_font = _safe_font(_named_value(typography, aliases))
        resolved_type[role] = parsed_font or fallback_type.get(role, "Arial")
        type_sources[role] = "imported" if parsed_font else "retained"

    name = (
        _value(payload.get("name")) or _value(metadata.get("name")) or "Imported design"
    )
    description = (
        _value(payload.get("description"))
        or "Custom design interpreted from DESIGN.md frontmatter."
    )
    detected = [
        f"{sum(1 for aliases in color_aliases.values() if _safe_color(_named_value(colors, aliases)))} color roles",
        f"{sum(1 for aliases in type_aliases.values() if _safe_font(_named_value(typography, aliases)))} typography roles",
    ]
    warnings = []
    if ignored_colors:
        warnings.append(f"Ignored non-hex values for: {', '.join(ignored_colors)}.")
    if not colors:
        warnings.append(
            "No colors were detected; the current preview colors will be retained."
        )
    if not typography:
        warnings.append(
            "No typography tokens were detected; the current preview type will be retained."
        )
    elif any(source == "imported" for source in type_sources.values()):
        warnings.append(
            "Imported font families use a local fallback when the named font is not available in this browser."
        )
    contrast_pairs = (
        ("accent", "paper", "accent text on the page"),
        ("paper", "primary", "ticker text on the primary color"),
        ("quiet", "surface", "quiet text on section surfaces"),
    )
    for foreground, background, label in contrast_pairs:
        ratio = _contrast(resolved_colors[foreground], resolved_colors[background])
        if ratio < 4.5:
            warnings.append(
                f"Low contrast ({ratio:.2f}:1) for {label}; use 4.5:1 or higher for small text."
            )
    normalized_body = re.sub(
        r"^---\s*\n.*?\n---",
        "",
        markdown.lstrip("\ufeff").replace("\r\n", "\n"),
        count=1,
        flags=re.DOTALL,
    ).strip()
    if normalized_body:
        warnings.append(
            "Markdown guidance below the frontmatter is stored, but this local parser does not convert prose into tokens yet."
        )

    return DesignInterpretation(
        name=name[:100],
        description=description[:500],
        tokens={"colors": resolved_colors, "typography": resolved_type},
        sources={"colors": color_sources, "typography": type_sources},
        detected=detected,
        warnings=warnings,
    )


@router.post("/resumes/{upload_id}/portfolio", response_model=PortfolioDraftResponse)
def generate_portfolio_draft(
    upload_id: int, db: Session = Depends(get_db)
) -> PortfolioDraftResponse:
    """Create or refresh one local draft from the latest reviewed resume data."""

    _require_local_environment()
    upload = db.get(ResumeUpload, upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="Résumé upload not found.")
    if upload.extraction_status != "completed" or not upload.extracted_data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Review and save the extracted résumé before generating a portfolio.",
        )

    design = (
        db.query(DesignSystem)
        .filter(DesignSystem.slug == DEFAULT_DESIGN_SLUG)
        .one_or_none()
    )
    template = (
        db.query(WireframeTemplate)
        .filter(WireframeTemplate.slug == DEFAULT_TEMPLATE_SLUG)
        .one_or_none()
    )
    if design is None or template is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The default portfolio design is not installed. Run the local database migration.",
        )

    data = ExtractedResumeData.model_validate(upload.extracted_data)
    portfolio = (
        db.query(Portfolio)
        .filter(Portfolio.resume_upload_id == upload.id)
        .one_or_none()
    )
    is_new_portfolio = portfolio is None
    if portfolio is None:
        title_source = (
            data.contact.name.strip()
            or Path(upload.original_filename or "Portfolio").stem
        )
        portfolio = Portfolio(
            user_id=upload.user_id,
            resume_upload_id=upload.id,
            title=f"{title_source} — Portfolio",
            slug=_available_slug(
                db,
                _slug_base(data.contact.name, upload.original_filename or "portfolio"),
            ),
            design_system_id=design.id,
            template_id=template.id,
            status="draft",
        )
        db.add(portfolio)
        db.flush()
    elif portfolio.design_system_id is None or portfolio.template_id is None:
        portfolio.design_system_id = design.id
        portfolio.template_id = template.id

    try:
        portfolio.content_model = _merge_user_content(
            _canonical_content(data), portfolio.content_model
        )
        portfolio.content_version = 1
        if not is_new_portfolio:
            _touch_portfolio(portfolio)
        _sync_portfolio_sections(db, portfolio)
        db.commit()
        db.refresh(portfolio)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The portfolio draft could not be stored. Please try again.",
        ) from exc

    return _response(db, portfolio)


@router.get("/portfolio-options", response_model=PortfolioOptionsResponse)
def portfolio_options(db: Session = Depends(get_db)) -> PortfolioOptionsResponse:
    _require_local_environment()
    designs = (
        db.query(DesignSystem)
        .filter(DesignSystem.is_public.is_(True))
        .order_by(DesignSystem.id)
        .all()
    )
    templates = (
        db.query(WireframeTemplate)
        .filter(WireframeTemplate.is_public.is_(True))
        .order_by(WireframeTemplate.id)
        .all()
    )
    return PortfolioOptionsResponse(
        design_systems=[_design_type(design) for design in designs],
        templates=[_template_type(template) for template in templates],
    )


@router.get("/portfolios/{portfolio_id}", response_model=PortfolioDraftResponse)
def get_portfolio_draft(
    portfolio_id: int, db: Session = Depends(get_db)
) -> PortfolioDraftResponse:
    """Return the latest local draft for the standalone preview route."""

    _require_local_environment()
    return _response(db, _portfolio(db, portfolio_id))


def _validated_content_value(value: Any, current: Any) -> Any:
    if isinstance(current, list):
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise HTTPException(
                status_code=422,
                detail="List fields must contain text items.",
            )
        if len(value) > 50 or any(len(item) > 2_000 for item in value):
            raise HTTPException(
                status_code=422,
                detail="That content exceeds the supported item or character limit.",
            )
        return [item.strip() for item in value if item.strip()]
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail="Text fields require a text value.")
    if len(value) > 100_000:
        raise HTTPException(
            status_code=422,
            detail="That content exceeds the 100,000 character limit.",
        )
    return value.strip()


@router.put("/portfolios/{portfolio_id}/content", response_model=PortfolioDraftResponse)
def edit_portfolio_content(
    portfolio_id: int,
    source: PortfolioContentEdit,
    db: Session = Depends(get_db),
) -> PortfolioDraftResponse:
    """Update canonical portfolio copy without changing reviewed résumé evidence."""

    _require_local_environment()
    portfolio = _portfolio(db, portfolio_id)
    content = copy.deepcopy(portfolio.content_model or {})
    if content.get("version") != 1:
        raise HTTPException(
            status_code=409,
            detail="Refresh this portfolio from the reviewed résumé before editing its content.",
        )
    for edit in source.fields:
        field = _content_field_by_id(content, edit.field_id)
        if field is None:
            raise HTTPException(
                status_code=404,
                detail=f"Portfolio field {edit.field_id} was not found.",
            )
        if edit.hidden and field.get("importance") == "required":
            raise HTTPException(
                status_code=422,
                detail=f"{field.get('label', 'This field')} is required and cannot be hidden.",
            )
        field["value"] = _validated_content_value(edit.value, field.get("value"))
        field["provenance"] = "user-authored"
        field["source_refs"] = ["user.portfolio_edit"]
        field["confidence"] = 1.0
        field["approval_state"] = "approved"
        field["status"] = (
            "hidden"
            if edit.hidden
            else "ready"
            if _has_content(field["value"])
            else "blocking_gap"
            if field.get("importance") == "required"
            else "optional_gap"
        )

    if source.featured_role_ids is not None:
        role_ids = {
            role.get("id")
            for role in content.get("role_stories", [])
            if isinstance(role, dict)
        }
        featured = list(dict.fromkeys(source.featured_role_ids))
        if not featured or any(role_id not in role_ids for role_id in featured):
            raise HTTPException(
                status_code=422,
                detail="Choose at least one role that belongs to this portfolio.",
            )
        experience_contract = next(
            (
                section
                for section in (portfolio.template.sections or [])
                if isinstance(section, dict) and section.get("key") == "experience"
            ),
            {},
        )
        max_items = experience_contract.get("max_items")
        if isinstance(max_items, int) and len(featured) > max_items:
            raise HTTPException(
                status_code=422,
                detail=f"This wireframe can feature at most {max_items} roles.",
            )
        content["featured_role_ids"] = featured
        content["selection_approved"] = True

    if source.section_visibility is not None:
        if source.section_visibility.get("hero") is False:
            raise HTTPException(
                status_code=422, detail="The hero section must remain visible."
            )
        if source.section_visibility.get("experience") is False:
            raise HTTPException(
                status_code=422, detail="The experience section must remain visible."
            )
        visibility = content.setdefault("section_visibility", {})
        visibility.update(source.section_visibility)

    portfolio.content_model = content
    portfolio.content_version = 1
    _touch_portfolio(portfolio)
    _sync_portfolio_sections(db, portfolio)
    db.commit()
    db.refresh(portfolio)
    return _response(db, portfolio)


@router.post(
    "/portfolios/{portfolio_id}/wireframes/interpret",
    response_model=WireframeInterpretation,
)
def interpret_portfolio_wireframe(
    portfolio_id: int,
    desktop: UploadFile = File(...),
    mobile: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
) -> WireframeInterpretation:
    """Analyze a wireframe without changing the saved portfolio."""

    _require_local_environment()
    _portfolio(db, portfolio_id)
    max_bytes = get_settings().max_wireframe_size_bytes
    desktop_file = _wireframe_file(desktop, max_bytes)
    mobile_file = _wireframe_file(mobile, max_bytes) if mobile else None
    analysis = _interpret_wireframe_with_openai(desktop_file, mobile_file)
    return WireframeInterpretation(
        **analysis.model_dump(),
        desktop_filename=desktop_file[0],
        mobile_filename=mobile_file[0] if mobile_file else "",
    )


@router.post(
    "/portfolios/{portfolio_id}/wireframes",
    response_model=WireframeImportResponse,
)
def apply_portfolio_wireframe(
    portfolio_id: int,
    source: WireframeApproval,
    db: Session = Depends(get_db),
) -> WireframeImportResponse:
    """Store an explicitly approved interpretation as the user's private layout."""

    _require_local_environment()
    portfolio = _portfolio(db, portfolio_id)
    interpretation = source.interpretation
    _validate_wireframe_sections(interpretation.sections)
    slug = f"custom-wireframe-{portfolio.slug}"
    template = (
        db.query(WireframeTemplate).filter(WireframeTemplate.slug == slug).one_or_none()
    )
    layout = {
        "desktop": interpretation.desktop.model_dump(),
        "mobile": interpretation.mobile.model_dump(),
        "confidence": interpretation.confidence,
        "detected": interpretation.detected,
        "warnings": interpretation.warnings,
        "unsupported": interpretation.unsupported,
    }
    sections = [section.model_dump() for section in interpretation.sections]
    if template is None:
        template = WireframeTemplate(
            name=f"{interpretation.name[:80]} — {portfolio.id}",
            slug=slug,
            description=interpretation.description,
            sections=sections,
            layout=layout,
            is_public=False,
            owner_user_id=portfolio.user_id,
            source_desktop_filename=interpretation.desktop_filename[:255],
            source_mobile_filename=interpretation.mobile_filename[:255] or None,
        )
        db.add(template)
        db.flush()
    else:
        if template.owner_user_id != portfolio.user_id:
            raise HTTPException(
                status_code=409,
                detail="The custom wireframe identifier is already in use.",
            )
        template.name = f"{interpretation.name[:80]} — {portfolio.id}"
        template.description = interpretation.description
        template.sections = sections
        template.layout = layout
        template.source_desktop_filename = interpretation.desktop_filename[:255]
        template.source_mobile_filename = interpretation.mobile_filename[:255] or None
    portfolio.template_id = template.id
    _touch_portfolio(portfolio)
    db.commit()
    db.refresh(portfolio)
    return WireframeImportResponse(
        draft=_response(db, portfolio), interpretation=interpretation
    )


@router.put(
    "/portfolios/{portfolio_id}/appearance", response_model=PortfolioDraftResponse
)
def update_portfolio_appearance(
    portfolio_id: int,
    appearance: AppearanceInput,
    db: Session = Depends(get_db),
) -> PortfolioDraftResponse:
    _require_local_environment()
    portfolio = _portfolio(db, portfolio_id)
    if appearance.design_system_id is None and appearance.template_id is None:
        raise HTTPException(
            status_code=422, detail="Choose a design system or layout to update."
        )
    if appearance.design_system_id is not None:
        design = db.get(DesignSystem, appearance.design_system_id)
        if design is None or (
            not design.is_public and design.owner_user_id != portfolio.user_id
        ):
            raise HTTPException(status_code=404, detail="Design system not found.")
        portfolio.design_system_id = design.id
    if appearance.template_id is not None:
        template = db.get(WireframeTemplate, appearance.template_id)
        if template is None or (
            not template.is_public and template.owner_user_id != portfolio.user_id
        ):
            raise HTTPException(status_code=404, detail="Portfolio layout not found.")
        portfolio.template_id = template.id
    _touch_portfolio(portfolio)
    db.commit()
    db.refresh(portfolio)
    return _response(db, portfolio)


@router.post(
    "/portfolios/{portfolio_id}/design-md/interpret",
    response_model=DesignInterpretation,
)
def interpret_portfolio_design(
    portfolio_id: int,
    source: DesignMarkdownInput,
    db: Session = Depends(get_db),
) -> DesignInterpretation:
    _require_local_environment()
    portfolio = _portfolio(db, portfolio_id)
    return interpret_design_markdown(
        source.markdown, _resolved_design_tokens(portfolio.design_system)
    )


@router.post(
    "/portfolios/{portfolio_id}/design-system/clone",
    response_model=PortfolioDraftResponse,
)
def clone_portfolio_design(
    portfolio_id: int, db: Session = Depends(get_db)
) -> PortfolioDraftResponse:
    """Create or rebase a private design without mutating its public starter."""

    _require_local_environment()
    portfolio = _portfolio(db, portfolio_id)
    current = portfolio.design_system
    if not current.is_public and current.owner_user_id == portfolio.user_id:
        return _response(db, portfolio)
    slug = f"custom-{portfolio.slug}"
    design = db.query(DesignSystem).filter(DesignSystem.slug == slug).one_or_none()
    if design is None:
        design = DesignSystem(
            name=f"Custom {current.name} — {portfolio.id}",
            slug=slug,
            description=f"Private customization of {current.name}.",
            tokens={},
            token_overrides={},
            base_design_system_id=current.id,
            is_public=False,
            owner_user_id=portfolio.user_id,
        )
        db.add(design)
        db.flush()
    else:
        if design.owner_user_id != portfolio.user_id:
            raise HTTPException(
                status_code=409,
                detail="The custom design identifier is already in use.",
            )
        design.name = f"Custom {current.name} — {portfolio.id}"
        design.description = f"Private customization of {current.name}."
        design.tokens = {}
        design.token_overrides = {}
        design.base_design_system_id = current.id
        design.source_markdown = None
    portfolio.design_system_id = design.id
    _touch_portfolio(portfolio)
    db.commit()
    db.refresh(portfolio)
    return _response(db, portfolio)


@router.put(
    "/portfolios/{portfolio_id}/design-system",
    response_model=DesignEditResponse,
)
def edit_portfolio_design(
    portfolio_id: int,
    source: DesignEditorInput,
    db: Session = Depends(get_db),
) -> DesignEditResponse:
    """Persist supported overrides on a private design clone."""

    _require_local_environment()
    portfolio = _portfolio(db, portfolio_id)
    design = portfolio.design_system
    if design.is_public or design.owner_user_id != portfolio.user_id:
        raise HTTPException(
            status_code=409,
            detail="Customize this public design before editing it.",
        )
    design.token_overrides = _validated_overrides(source)
    design.tokens = {}
    design.source_markdown = None
    if source.name:
        design.name = f"{source.name.strip()} — {portfolio.id}"
    _touch_portfolio(portfolio)
    db.commit()
    db.refresh(portfolio)
    resolved = _resolved_design_tokens(design)
    return DesignEditResponse(
        draft=_response(db, portfolio), warnings=_design_warnings(resolved)
    )


@router.post(
    "/portfolios/{portfolio_id}/design-md", response_model=DesignImportResponse
)
def apply_portfolio_design(
    portfolio_id: int,
    source: DesignMarkdownInput,
    db: Session = Depends(get_db),
) -> DesignImportResponse:
    _require_local_environment()
    portfolio = _portfolio(db, portfolio_id)
    interpretation = interpret_design_markdown(
        source.markdown, _resolved_design_tokens(portfolio.design_system)
    )
    current = portfolio.design_system
    base = current if current.is_public else current.base_design_system
    base_tokens = _resolved_design_tokens(base) if base else {}
    overrides = {
        group: {
            key: value
            for key, value in interpretation.tokens.get(group, {}).items()
            if value != base_tokens.get(group, {}).get(key)
        }
        for group in ("colors", "typography")
    }
    slug = f"custom-{portfolio.slug}"
    design = db.query(DesignSystem).filter(DesignSystem.slug == slug).one_or_none()
    if design is None:
        design = DesignSystem(
            name=f"{interpretation.name[:88]} — {portfolio.id}",
            slug=slug,
            description=interpretation.description,
            tokens={} if base else interpretation.tokens,
            token_overrides=overrides if base else {},
            base_design_system_id=base.id if base else None,
            is_public=False,
            owner_user_id=portfolio.user_id,
            source_markdown=source.markdown,
        )
        db.add(design)
        db.flush()
    else:
        if design.owner_user_id != portfolio.user_id:
            raise HTTPException(
                status_code=409,
                detail="The custom design identifier is already in use.",
            )
        design.name = f"{interpretation.name[:88]} — {portfolio.id}"
        design.description = interpretation.description
        design.tokens = {} if base else interpretation.tokens
        design.token_overrides = overrides if base else {}
        design.base_design_system_id = base.id if base else None
        design.source_markdown = source.markdown
    portfolio.design_system_id = design.id
    _touch_portfolio(portfolio)
    db.commit()
    db.refresh(portfolio)
    return DesignImportResponse(
        draft=_response(db, portfolio), interpretation=interpretation
    )


@router.post(
    "/portfolios/{portfolio_id}/commit", response_model=PortfolioCommitResponse
)
def commit_portfolio_configuration(
    portfolio_id: int,
    source: PortfolioCommitInput,
    db: Session = Depends(get_db),
) -> PortfolioCommitResponse:
    """Freeze the reviewed editor state into a self-contained local draft snapshot."""

    _require_local_environment()
    portfolio = _portfolio(db, portfolio_id)
    if source.expected_revision != portfolio.builder_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This preview is stale. Load the latest saved draft before continuing.",
        )
    readiness = _content_readiness(portfolio.content_model or {}, portfolio.template)
    if any(gap.severity == "blocking" for gap in readiness.gaps):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Resolve the required content gaps before starting the website build.",
        )

    committed_at = datetime.now(timezone.utc)
    next_revision = (portfolio.builder_revision or 0) + 1
    snapshot = {
        "version": 1,
        "portfolio_id": portfolio.id,
        "revision": next_revision,
        "committed_at": committed_at.isoformat(),
        "design_system": _design_type(portfolio.design_system).model_dump(),
        "template": _template_type(portfolio.template).model_dump(),
        "content_model": copy.deepcopy(portfolio.content_model or {}),
        "sections": [
            {"key": key, "content": value, "order_index": index}
            for index, (key, value) in enumerate(
                _materialized_sections(portfolio.content_model or {})
            )
        ],
        "readiness": readiness.model_dump(),
    }
    portfolio.builder_revision = next_revision
    portfolio.configuration_status = "configured"
    portfolio.configuration_snapshot = snapshot
    portfolio.configured_at = committed_at
    db.commit()
    db.refresh(portfolio)
    return PortfolioCommitResponse(draft=_response(db, portfolio), snapshot=snapshot)

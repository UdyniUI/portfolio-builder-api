"""Generate a local, unpublished portfolio draft from reviewed resume data."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
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

router = APIRouter(prefix="/resumes", tags=["portfolios"])

DEFAULT_DESIGN_SLUG = "night-shift"
DEFAULT_TEMPLATE_SLUG = "career-narrative"


class DraftDesign(BaseModel):
    id: int
    name: str
    slug: str
    description: Optional[str]
    tokens: dict[str, Any]


class DraftTemplate(BaseModel):
    id: int
    name: str
    slug: str
    description: Optional[str]


class DraftSection(BaseModel):
    key: str
    content: dict[str, Any]
    order_index: int


class PortfolioDraftResponse(BaseModel):
    id: int
    resume_upload_id: int
    title: str
    slug: str
    status: str
    design_system: DraftDesign
    template: DraftTemplate
    sections: list[DraftSection]


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


def _section_payloads(data: ExtractedResumeData) -> list[tuple[str, dict[str, Any]]]:
    contact = data.contact
    sections = data.sections
    return [
        (
            "hero",
            {
                "name": contact.name,
                "headline": sections.summary.splitlines()[0]
                if sections.summary
                else "",
                "location": contact.location,
                "links": contact.links,
            },
        ),
        ("about", {"body": sections.summary}),
        ("skills", {"items": _split_skills(sections.skills)}),
        ("experience", {"body": sections.experience}),
        ("education", {"body": sections.education}),
        ("projects", {"body": sections.projects}),
        (
            "contact",
            {
                "email": contact.email,
                "phone": contact.phone,
                "location": contact.location,
                "links": contact.links,
            },
        ),
    ]


def _response(db: Session, portfolio: Portfolio) -> PortfolioDraftResponse:
    sections = (
        db.query(PortfolioData)
        .filter(PortfolioData.portfolio_id == portfolio.id)
        .order_by(PortfolioData.order_index, PortfolioData.id)
        .all()
    )
    return PortfolioDraftResponse(
        id=portfolio.id,
        resume_upload_id=portfolio.resume_upload_id,
        title=portfolio.title,
        slug=portfolio.slug,
        status=portfolio.status,
        design_system=DraftDesign(
            id=portfolio.design_system.id,
            name=portfolio.design_system.name,
            slug=portfolio.design_system.slug,
            description=portfolio.design_system.description,
            tokens=portfolio.design_system.tokens,
        ),
        template=DraftTemplate(
            id=portfolio.template.id,
            name=portfolio.template.name,
            slug=portfolio.template.slug,
            description=portfolio.template.description,
        ),
        sections=[
            DraftSection(
                key=item.section_key, content=item.content, order_index=item.order_index
            )
            for item in sections
        ],
    )


@router.post("/{upload_id}/portfolio", response_model=PortfolioDraftResponse)
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
    else:
        portfolio.design_system_id = design.id
        portfolio.template_id = template.id

    try:
        existing = {
            section.section_key: section for section in portfolio.portfolio_data
        }
        for index, (key, content) in enumerate(_section_payloads(data)):
            section = existing.get(key)
            if section is None:
                db.add(
                    PortfolioData(
                        portfolio_id=portfolio.id,
                        section_key=key,
                        content=content,
                        order_index=index,
                    )
                )
            else:
                section.content = content
                section.order_index = index
        db.commit()
        db.refresh(portfolio)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The portfolio draft could not be stored. Please try again.",
        ) from exc

    return _response(db, portfolio)

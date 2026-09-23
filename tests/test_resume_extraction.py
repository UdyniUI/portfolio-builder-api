from io import BytesIO
from pathlib import Path
from typing import Optional
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app.config import get_settings
from app.database.connection import Base, SessionLocal, engine
from app.database.models import (
    DesignSystem,
    Portfolio,
    PortfolioData,
    ResumeUpload,
    WireframeTemplate,
)
from app.main import app
from app.portfolio_generation import WireframeAnalysis, _experience_items


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def docx_with_text(lines: list[str]) -> bytes:
    paragraphs = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in lines)
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{paragraphs}</w:body></w:document>"
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def pdf_with_text(lines: list[str]) -> bytes:
    escaped = [
        line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        for line in lines
    ]
    operations = ["BT", "/F1 12 Tf", "72 740 Td", "16 TL"]
    for index, line in enumerate(escaped):
        if index:
            operations.append("T*")
        operations.append(f"({line}) Tj")
    operations.append("ET")
    stream = "\n".join(operations).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(content))
        content.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref_offset = len(content)
    content.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    content.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode())
    content.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(content)


def upload_resume(
    client: TestClient, filename: str, content: bytes, content_type: str
) -> int:
    response = client.post("/upload", files={"file": (filename, content, content_type)})
    assert response.status_code == 201
    return response.json()["id"]


def wireframe_section(
    key: str,
    label: str,
    slots: list[str],
    *,
    required_slots: Optional[list[str]] = None,
    min_items: int = 0,
    max_items: int = 1,
    item_limits: Optional[dict[str, int]] = None,
    overflow: str = "condense",
    fallback: str = "collapse",
) -> dict:
    return {
        "key": key,
        "label": label,
        "width": "full" if key in {"hero", "experience", "contact"} else "content",
        "alignment": "left",
        "emphasis": "primary" if key in {"hero", "experience"} else "standard",
        "group": key,
        "slots": slots,
        "required_slots": required_slots or [],
        "min_items": min_items,
        "max_items": max_items,
        "item_limits": item_limits or {},
        "overflow": overflow,
        "fallback": fallback,
    }


def seed_portfolio_options():
    with SessionLocal() as db:
        db.add_all(
            [
                DesignSystem(
                    name="Night Shift",
                    slug="night-shift",
                    description="Dark default",
                    tokens={
                        "colors": {
                            "paper": "#090B0F",
                            "surface": "#11151C",
                            "ink": "#F5F7F2",
                            "primary": "#D8FF5F",
                            "accent": "#7887FF",
                            "quiet": "#9BA5B5",
                            "line": "#293140",
                        },
                        "typography": {
                            "heading": "Arial Narrow",
                            "body": "Arial",
                            "mono": "ui-monospace",
                        },
                    },
                ),
                DesignSystem(
                    name="Tech Forward",
                    slug="tech-forward",
                    description="Light technical system",
                    tokens={
                        "colors": {
                            "paper": "#F8FAFC",
                            "ink": "#0F172A",
                            "primary": "#0891B2",
                            "accent": "#22D3EE",
                        }
                    },
                ),
                WireframeTemplate(
                    name="Executive Brief",
                    slug="executive-brief",
                    description="Concise profile",
                    sections=[
                        wireframe_section(
                            "hero",
                            "Identity",
                            ["name", "headline"],
                            required_slots=["name", "headline"],
                            min_items=1,
                            overflow="show-all",
                            fallback="show-available",
                        ),
                        wireframe_section("about", "Positioning", ["body"]),
                        wireframe_section(
                            "experience",
                            "Selected Proof",
                            ["role", "summary", "highlights", "outcomes"],
                            required_slots=["role", "highlights"],
                            min_items=1,
                            max_items=2,
                            item_limits={"highlights": 2, "outcomes": 1, "skills": 0},
                            overflow="rank",
                            fallback="raw-text",
                        ),
                        wireframe_section(
                            "contact", "Contact", ["email", "phone", "links"]
                        ),
                    ],
                    layout={
                        "desktop": {
                            "max_width": "narrow",
                            "columns": 1,
                            "navigation": "none",
                        },
                        "mobile": {
                            "max_width": "narrow",
                            "columns": 1,
                            "navigation": "none",
                        },
                    },
                ),
                WireframeTemplate(
                    name="Case Study Ledger",
                    slug="case-study-ledger",
                    description="Role projects first",
                    sections=[
                        wireframe_section(
                            "hero",
                            "Positioning",
                            ["name", "headline"],
                            required_slots=["name", "headline"],
                            min_items=1,
                            overflow="show-all",
                            fallback="show-available",
                        ),
                        wireframe_section(
                            "experience",
                            "Featured Work",
                            ["role", "summary", "highlights", "outcomes", "skills"],
                            required_slots=["role", "highlights"],
                            min_items=1,
                            max_items=4,
                            item_limits={"highlights": 3, "outcomes": 2, "skills": 4},
                            fallback="raw-text",
                        ),
                        wireframe_section(
                            "skills", "Capability Stack", ["items"], max_items=3
                        ),
                        wireframe_section("projects", "Additional Work", ["body"]),
                        wireframe_section(
                            "contact", "Contact", ["email", "phone", "links"]
                        ),
                    ],
                    layout={
                        "desktop": {
                            "max_width": "wide",
                            "columns": 1,
                            "navigation": "compact",
                        },
                        "mobile": {
                            "max_width": "standard",
                            "columns": 1,
                            "navigation": "compact",
                        },
                    },
                ),
                WireframeTemplate(
                    name="Career Atlas",
                    slug="career-atlas",
                    description="Comprehensive career journey",
                    sections=[
                        wireframe_section(
                            "hero",
                            "Identity and Proof",
                            ["name", "headline", "proof_facts"],
                            required_slots=["name", "headline"],
                            min_items=1,
                            fallback="show-available",
                        ),
                        wireframe_section(
                            "skills", "Core Competencies", ["items"], max_items=4
                        ),
                        wireframe_section("about", "Featured Story", ["body"]),
                        wireframe_section(
                            "experience",
                            "Professional Journey",
                            ["role", "summary", "highlights", "outcomes", "skills"],
                            required_slots=["role"],
                            min_items=1,
                            max_items=5,
                            item_limits={"highlights": 3, "outcomes": 2, "skills": 3},
                            fallback="raw-text",
                        ),
                        wireframe_section("projects", "Achievements", ["body"]),
                        wireframe_section("education", "Education", ["body"]),
                        wireframe_section(
                            "contact", "Contact", ["email", "phone", "links"]
                        ),
                    ],
                    layout={
                        "desktop": {
                            "max_width": "wide",
                            "columns": 2,
                            "navigation": "inline",
                        },
                        "mobile": {
                            "max_width": "standard",
                            "columns": 1,
                            "navigation": "compact",
                        },
                    },
                ),
            ]
        )
        db.commit()


def test_docx_extraction_structures_and_persists_review_data():
    content = docx_with_text(
        [
            "Udayani Chava",
            "udayani@example.com",
            "+1 416 555 0199",
            "linkedin.com/in/udayani",
            "Professional Summary",
            "Product designer building trustworthy systems.",
            "Experience",
            "Lead Designer — PortfolioOS",
            "Education",
            "BDes, Interaction Design",
            "Skills",
            "Design systems, research, prototyping",
            "Projects",
            "PortfolioOS résumé workflow",
        ]
    )

    with TestClient(app) as client:
        upload_id = upload_resume(
            client,
            "resume.docx",
            content,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        response = client.post(f"/resumes/{upload_id}/extract")
        fetched = client.get(f"/resumes/{upload_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["extraction_status"] == "completed"
    assert payload["extracted_data"]["contact"]["name"] == "Udayani Chava"
    assert payload["extracted_data"]["contact"]["email"] == "udayani@example.com"
    assert "Lead Designer" in payload["extracted_data"]["sections"]["experience"]
    assert fetched.json() == payload

    with SessionLocal() as db:
        upload = db.get(ResumeUpload, upload_id)
        assert upload.extraction_status == "completed"
        assert upload.extracted_data["schema_version"] == 1


def test_pdf_extraction_reads_selectable_text():
    content = pdf_with_text(
        [
            "Alex Morgan",
            "alex@example.com",
            "Summary",
            "Platform engineer",
            "Skills",
            "Python PostgreSQL",
        ]
    )

    with TestClient(app) as client:
        upload_id = upload_resume(client, "resume.pdf", content, "application/pdf")
        response = client.post(f"/resumes/{upload_id}/extract")

    assert response.status_code == 200
    payload = response.json()
    assert payload["extraction_status"] == "completed"
    assert payload["extracted_data"]["contact"]["name"] == "Alex Morgan"
    assert "Python PostgreSQL" in payload["extracted_data"]["sections"]["skills"]
    assert all(
        "projects" not in warning for warning in payload["extracted_data"]["warnings"]
    )


def test_extraction_failure_is_persisted_and_can_be_retried():
    content = docx_with_text([])

    with TestClient(app) as client:
        upload_id = upload_resume(
            client,
            "empty.docx",
            content,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        response = client.post(f"/resumes/{upload_id}/extract")
        retried = client.post(f"/resumes/{upload_id}/extract")

    assert response.json()["extraction_status"] == "failed"
    assert "No selectable text" in response.json()["error"]
    assert retried.json()["extraction_status"] == "failed"

    with SessionLocal() as db:
        upload = db.get(ResumeUpload, upload_id)
        assert upload.extraction_status == "failed"
        assert "No selectable text" in upload.extracted_data["error"]


def test_review_corrections_are_validated_and_saved():
    content = docx_with_text(["Taylor Doe", "Summary", "Original summary"])

    with TestClient(app) as client:
        upload_id = upload_resume(
            client,
            "resume.docx",
            content,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        extracted = client.post(f"/resumes/{upload_id}/extract").json()[
            "extracted_data"
        ]
        extracted["contact"]["location"] = "Toronto, Canada"
        extracted["sections"]["summary"] = "Corrected and verified summary."
        response = client.put(f"/resumes/{upload_id}/extracted-data", json=extracted)

    assert response.status_code == 200
    saved = response.json()["extracted_data"]
    assert saved["contact"]["location"] == "Toronto, Canada"
    assert saved["sections"]["summary"] == "Corrected and verified summary."


def test_reviewed_resume_generates_one_refreshable_unpublished_portfolio():
    content = docx_with_text(
        [
            "Taylor Doe",
            "taylor@example.com",
            "Summary",
            "Platform designer building clear systems.",
            "Experience",
            "Lead Designer — Signal Works",
            "January 2023 – Present",
            "Overview: Led the portfolio platform redesign.",
            "- Built a reusable design system for four teams.",
            "Impact: Reduced portfolio setup time by 40%.",
            "Skills: Product strategy, Design systems, Accessibility",
            "Product Designer at Northstar Labs",
            "2020 – 2022",
            "- Shipped research-backed onboarding improvements.",
            "Education",
            "BDes",
            "Skills",
            "Research, Prototyping, Design systems",
            "Projects",
            "PortfolioOS",
        ]
    )

    with SessionLocal() as db:
        db.add(
            DesignSystem(
                name="Night Shift",
                slug="night-shift",
                description="Dark default",
                tokens={"colors": {"paper": "#090B0F", "primary": "#D8FF5F"}},
            )
        )
        db.add(
            WireframeTemplate(
                name="Executive Brief",
                slug="executive-brief",
                description="Concise profile",
                sections=[
                    {"key": "hero"},
                    {"key": "about"},
                    {"key": "experience"},
                    {"key": "contact"},
                ],
            )
        )
        db.commit()

    with TestClient(app) as client:
        upload_id = upload_resume(
            client,
            "resume.docx",
            content,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        client.post(f"/resumes/{upload_id}/extract")
        first = client.post(f"/resumes/{upload_id}/portfolio")
        second = client.post(f"/resumes/{upload_id}/portfolio")
        edited = client.put(
            f"/portfolios/{first.json()['id']}/content",
            json={
                "fields": [
                    {
                        "field_id": "identity.headline",
                        "value": "Designing trustworthy workflow products.",
                    },
                    {
                        "field_id": "role-2.outcomes",
                        "value": [
                            "Improved onboarding with verified research evidence."
                        ],
                    },
                ],
                "featured_role_ids": ["role-2"],
            },
        )
        refreshed = client.post(f"/resumes/{upload_id}/portfolio")

    assert first.status_code == 200
    payload = first.json()
    assert payload["status"] == "draft"
    assert payload["design_system"]["slug"] == "night-shift"
    assert payload["template"]["slug"] == "executive-brief"
    assert payload["content_model"]["version"] == 1
    assert payload["content_model"]["fields"]["identity.name"] == {
        "id": "identity.name",
        "label": "Name",
        "section_key": "hero",
        "value": "Taylor Doe",
        "provenance": "extracted",
        "source_refs": ["resume.contact.name"],
        "confidence": 1.0,
        "approval_state": "approved",
        "importance": "required",
        "status": "ready",
    }
    assert any(
        gap["field_id"] == "role-2.outcomes" for gap in payload["readiness"]["gaps"]
    )
    assert [section["key"] for section in payload["sections"]] == [
        "hero",
        "about",
        "experience",
        "contact",
        "skills",
        "education",
        "projects",
    ]
    experience = payload["sections"][2]["content"]
    assert experience["body"].startswith("Lead Designer — Signal Works")
    assert experience["items"] == [
        {
            "id": "role-1",
            "role": "Lead Designer",
            "company": "Signal Works",
            "dates": "January 2023 – Present",
            "summary": "Led the portfolio platform redesign.",
            "highlights": ["Built a reusable design system for four teams."],
            "outcomes": ["Reduced portfolio setup time by 40%."],
            "skills": ["Product strategy", "Design systems", "Accessibility"],
        },
        {
            "id": "role-2",
            "role": "Product Designer",
            "company": "Northstar Labs",
            "dates": "2020 – 2022",
            "summary": "",
            "highlights": ["Shipped research-backed onboarding improvements."],
            "outcomes": [],
            "skills": [],
        },
    ]
    assert second.json()["id"] == payload["id"]
    assert edited.status_code == 200
    assert (
        edited.json()["content_model"]["fields"]["identity.headline"]["provenance"]
        == "user-authored"
    )
    assert edited.json()["sections"][0]["content"]["headline"] == (
        "Designing trustworthy workflow products."
    )
    assert edited.json()["sections"][2]["content"]["items"][0]["role"] == (
        "Product Designer"
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["sections"][0]["content"]["headline"] == (
        "Designing trustworthy workflow products."
    )
    assert refreshed.json()["content_model"]["featured_role_ids"] == ["role-2"]

    with SessionLocal() as db:
        assert db.query(Portfolio).count() == 1
        assert db.query(PortfolioData).count() == 7


def test_portfolio_commit_is_versioned_self_contained_and_invalidated_by_edits():
    seed_portfolio_options()
    content = docx_with_text(
        [
            "Taylor Doe",
            "taylor@example.com",
            "Summary",
            "Product designer building evidence-led workflow systems.",
            "Experience",
            "Lead Designer — Signal Works",
            "January 2023 – Present",
            "- Built a reusable portfolio workflow.",
            "Impact: Reduced setup time by 40%.",
        ]
    )

    with TestClient(app) as client:
        upload_id = upload_resume(
            client,
            "resume.docx",
            content,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        client.post(f"/resumes/{upload_id}/extract")
        draft = client.post(f"/resumes/{upload_id}/portfolio").json()
        committed = client.post(
            f"/portfolios/{draft['id']}/commit",
            json={"expected_revision": draft["builder"]["revision"]},
        )
        stale = client.post(
            f"/portfolios/{draft['id']}/commit",
            json={"expected_revision": draft["builder"]["revision"]},
        )
        edited = client.put(
            f"/portfolios/{draft['id']}/content",
            json={"section_visibility": {"about": False}},
        )

    assert committed.status_code == 200
    payload = committed.json()
    assert payload["draft"]["builder"]["configuration_status"] == "configured"
    assert payload["snapshot"]["revision"] == draft["builder"]["revision"] + 1
    assert payload["snapshot"]["design_system"]["slug"] == "night-shift"
    assert payload["snapshot"]["template"]["slug"] == "executive-brief"
    assert (
        payload["snapshot"]["content_model"]["fields"]["identity.name"]["value"]
        == "Taylor Doe"
    )
    assert len(payload["snapshot"]["sections"]) == 7
    assert stale.status_code == 409
    assert "stale" in stale.json()["detail"].lower()
    assert edited.status_code == 200
    assert edited.json()["builder"]["configuration_status"] == "editing"
    assert edited.json()["builder"]["configured_at"] is None
    assert edited.json()["content_model"]["section_visibility"]["about"] is False

    with SessionLocal() as db:
        portfolio = db.get(Portfolio, draft["id"])
        assert portfolio is not None
        assert portfolio.configuration_snapshot is None


def test_experience_roles_require_explicit_structure_without_inventing_titles():
    assert _experience_items("Led a 2024 platform launch.\nImproved activation.") == []
    assert _experience_items(
        "Role: Senior Designer\n"
        "Company: Northstar Labs\n"
        "Impact: Increased adoption in 2024.\n"
        "Skills: Research; Prototyping"
    ) == [
        {
            "role": "Senior Designer",
            "company": "Northstar Labs",
            "dates": "",
            "summary": "",
            "highlights": [],
            "outcomes": ["Increased adoption in 2024."],
            "skills": ["Research", "Prototyping"],
        }
    ]
    assert _experience_items("Design Lead | Signal Works | 2021 – 2023") == [
        {
            "role": "Design Lead",
            "company": "Signal Works",
            "dates": "2021 – 2023",
            "summary": "",
            "highlights": [],
            "outcomes": [],
            "skills": [],
        }
    ]


def test_portfolio_appearance_and_design_markdown_are_previewed_then_persisted():
    seed_portfolio_options()
    content = docx_with_text(
        [
            "Taylor Doe",
            "taylor@example.com",
            "Summary",
            "Platform designer building clear systems.",
        ]
    )
    design_markdown = """---
name: Aurora Field
description: A confident custom direction.
colors:
  primary: '#F3FF8C'
  secondary: '#FF7A59'
  background: '#10131A'
  background-alt: '#171C26'
  text: '#F7F8F2'
  text-dim: '#B8C0CE'
  surface-border: '#354052'
typography:
  font-family-heading: 'Aptos Display, sans-serif'
  font-family-body: 'Aptos, sans-serif'
  font-family-mono: 'ui-monospace'
---

# Direction
Keep the work direct and readable.
"""

    with TestClient(app) as client:
        upload_id = upload_resume(
            client,
            "resume.docx",
            content,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        client.post(f"/resumes/{upload_id}/extract")
        draft = client.post(f"/resumes/{upload_id}/portfolio").json()
        options = client.get("/portfolio-options")

        assert options.status_code == 200
        option_payload = options.json()
        tech = next(
            item
            for item in option_payload["design_systems"]
            if item["slug"] == "tech-forward"
        )
        ledger = next(
            item
            for item in option_payload["templates"]
            if item["slug"] == "case-study-ledger"
        )
        assert [item["slug"] for item in option_payload["templates"]] == [
            "executive-brief",
            "case-study-ledger",
            "career-atlas",
        ]
        assert all(
            {
                "slots",
                "required_slots",
                "min_items",
                "max_items",
                "item_limits",
                "overflow",
                "fallback",
            }
            <= set(section)
            for template in option_payload["templates"]
            for section in template["sections"]
        )
        changed = client.put(
            f"/portfolios/{draft['id']}/appearance",
            json={
                "design_system_id": tech["id"],
                "template_id": ledger["id"],
            },
        )
        matrix = [
            client.put(
                f"/portfolios/{draft['id']}/appearance",
                json={
                    "design_system_id": design["id"],
                    "template_id": template["id"],
                },
            )
            for design in option_payload["design_systems"]
            for template in option_payload["templates"]
        ]
        rejected_public_edit = client.put(
            f"/portfolios/{draft['id']}/design-system",
            json={"colors": {"primary": "#FF7043"}},
        )
        cloned = client.post(f"/portfolios/{draft['id']}/design-system/clone")
        edited = client.put(
            f"/portfolios/{draft['id']}/design-system",
            json={
                "name": "Signal Edit",
                "colors": {"primary": "#FF7043"},
                "typography": {"heading": "Fraunces, Georgia, serif"},
            },
        )
        interpreted = client.post(
            f"/portfolios/{draft['id']}/design-md/interpret",
            json={"markdown": design_markdown},
        )
        partial = client.post(
            f"/portfolios/{draft['id']}/design-md/interpret",
            json={
                "markdown": "---\nname: Partial\ncolors:\n  primary: '#F3FF8C'\n  background: '#10131A'\n  text: '#F7F8F2'\n---"
            },
        )
        applied = client.post(
            f"/portfolios/{draft['id']}/design-md",
            json={"markdown": design_markdown},
        )
        reapplied = client.post(
            f"/portfolios/{draft['id']}/design-md",
            json={
                "markdown": design_markdown.replace("Aurora Field", "Aurora Field Two")
            },
        )
        invalid = client.post(
            f"/portfolios/{draft['id']}/design-md/interpret",
            json={"markdown": "# No frontmatter"},
        )

    assert changed.status_code == 200
    assert changed.json()["design_system"]["slug"] == "tech-forward"
    assert changed.json()["template"]["slug"] == "case-study-ledger"
    assert [section["key"] for section in changed.json()["sections"]] == [
        "hero",
        "experience",
        "skills",
        "projects",
        "contact",
        "about",
        "education",
    ]
    assert len(matrix) == 6
    assert all(response.status_code == 200 for response in matrix)
    assert rejected_public_edit.status_code == 409
    assert rejected_public_edit.json()["detail"] == (
        "Customize this public design before editing it."
    )
    assert {
        (response.json()["design_system"]["slug"], response.json()["template"]["slug"])
        for response in matrix
    } == {
        (design, template)
        for design in ("night-shift", "tech-forward")
        for template in ("executive-brief", "case-study-ledger", "career-atlas")
    }
    assert cloned.status_code == 200
    assert cloned.json()["design_system"]["is_custom"] is True
    assert cloned.json()["design_system"]["base_design_system_id"] == tech["id"]
    assert cloned.json()["design_system"]["token_overrides"] == {}
    assert edited.status_code == 200
    assert (
        edited.json()["draft"]["design_system"]["tokens"]["colors"]["primary"]
        == "#FF7043"
    )
    assert (
        edited.json()["draft"]["design_system"]["tokens"]["colors"]["paper"]
        == "#F8FAFC"
    )
    assert edited.json()["draft"]["design_system"]["token_overrides"] == {
        "colors": {"primary": "#FF7043"},
        "typography": {"heading": "Fraunces, Georgia, serif"},
    }
    with SessionLocal() as db:
        assert db.get(DesignSystem, tech["id"]).tokens["colors"]["primary"] == "#0891B2"
    assert interpreted.status_code == 200
    assert interpreted.json()["tokens"]["colors"]["paper"] == "#10131A"
    assert interpreted.json()["tokens"]["colors"]["surface"] == "#171C26"
    assert interpreted.json()["detected"] == ["7 color roles", "3 typography roles"]
    assert interpreted.json()["sources"]["colors"]["primary"] == "imported"
    assert any(
        "does not convert prose" in warning
        for warning in interpreted.json()["warnings"]
    )
    assert partial.json()["tokens"]["colors"]["surface"] == "#10131A"
    assert partial.json()["tokens"]["colors"]["quiet"] == "#F7F8F2"
    assert partial.json()["sources"]["colors"]["surface"] == "retained"
    assert applied.status_code == 200
    assert applied.json()["draft"]["design_system"]["is_custom"] is True
    assert (
        applied.json()["draft"]["design_system"]["tokens"]["colors"]["accent"]
        == "#FF7A59"
    )
    assert (
        reapplied.json()["draft"]["design_system"]["id"]
        == applied.json()["draft"]["design_system"]["id"]
    )
    assert invalid.status_code == 422
    with SessionLocal() as db:
        assert (
            db.query(DesignSystem).filter(DesignSystem.is_public.is_(False)).count()
            == 1
        )


def test_wireframe_is_reviewed_then_saved_as_a_private_layout(monkeypatch):
    seed_portfolio_options()
    content = docx_with_text(
        [
            "Taylor Doe",
            "taylor@example.com",
            "Summary",
            "Platform designer building clear systems.",
            "Experience",
            "Design Lead — Signal Works",
        ]
    )
    analysis = WireframeAnalysis.model_validate(
        {
            "name": "Editorial split",
            "description": "A two-column desktop story with a stacked mobile route.",
            "confidence": 0.88,
            "sections": [
                {
                    "key": "hero",
                    "label": "Hero",
                    "width": "full",
                    "alignment": "center",
                    "emphasis": "primary",
                    "group": "",
                },
                {
                    "key": "experience",
                    "label": "Role projects",
                    "width": "wide",
                    "alignment": "left",
                    "emphasis": "primary",
                    "group": "work",
                },
                {
                    "key": "skills",
                    "label": "Skills",
                    "width": "content",
                    "alignment": "left",
                    "emphasis": "standard",
                    "group": "support",
                },
                {
                    "key": "contact",
                    "label": "Contact",
                    "width": "full",
                    "alignment": "center",
                    "emphasis": "quiet",
                    "group": "",
                },
            ],
            "desktop": {"max_width": "wide", "columns": 2, "navigation": "inline"},
            "mobile": {"max_width": "standard", "columns": 1, "navigation": "compact"},
            "detected": ["Two-column desktop body"],
            "warnings": ["Mobile layout was derived"],
            "unsupported": [],
        }
    )
    monkeypatch.setattr(
        "app.portfolio_generation._interpret_wireframe_with_openai",
        lambda desktop, mobile: analysis,
    )

    with TestClient(app) as client:
        upload_id = upload_resume(
            client,
            "resume.docx",
            content,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        client.post(f"/resumes/{upload_id}/extract")
        draft = client.post(f"/resumes/{upload_id}/portfolio").json()
        interpreted = client.post(
            f"/portfolios/{draft['id']}/wireframes/interpret",
            files={"desktop": ("layout.png", b"\x89PNG\r\n\x1a\nmock", "image/png")},
        )
        payload = interpreted.json()
        payload["sections"][1]["alignment"] = "center"
        applied = client.post(
            f"/portfolios/{draft['id']}/wireframes",
            json={"interpretation": payload},
        )
        loaded = client.get(f"/portfolios/{draft['id']}")

    assert interpreted.status_code == 200
    assert payload["desktop_filename"] == "layout.png"
    assert applied.status_code == 200
    assert applied.json()["draft"]["template"]["is_custom"] is True
    assert applied.json()["draft"]["template"]["layout"]["desktop"]["columns"] == 2
    assert applied.json()["draft"]["template"]["sections"][1]["alignment"] == "center"
    assert [section["key"] for section in loaded.json()["sections"]] == [
        "hero",
        "experience",
        "skills",
        "contact",
    ]
    with SessionLocal() as db:
        private_layout = (
            db.query(WireframeTemplate)
            .filter(WireframeTemplate.is_public.is_(False))
            .one()
        )
        assert private_layout.owner_user_id is not None
        assert private_layout.source_desktop_filename == "layout.png"


def test_missing_upload_returns_not_found():
    with TestClient(app) as client:
        response = client.post("/resumes/999/extract")
    assert response.status_code == 404


def teardown_module():
    upload_dir = Path(get_settings().resume_upload_dir)
    for path in upload_dir.glob("*"):
        path.unlink(missing_ok=True)

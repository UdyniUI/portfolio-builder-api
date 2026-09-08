from io import BytesIO
from pathlib import Path
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
                name="Career Narrative",
                slug="career-narrative",
                description="Career sections",
                sections=[{"key": "hero"}],
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

    assert first.status_code == 200
    payload = first.json()
    assert payload["status"] == "draft"
    assert payload["design_system"]["slug"] == "night-shift"
    assert payload["template"]["slug"] == "career-narrative"
    assert [section["key"] for section in payload["sections"]] == [
        "hero",
        "about",
        "skills",
        "experience",
        "education",
        "projects",
        "contact",
    ]
    assert payload["sections"][2]["content"]["items"] == [
        "Research",
        "Prototyping",
        "Design systems",
    ]
    assert second.json()["id"] == payload["id"]

    with SessionLocal() as db:
        assert db.query(Portfolio).count() == 1
        assert db.query(PortfolioData).count() == 7


def test_missing_upload_returns_not_found():
    with TestClient(app) as client:
        response = client.post("/resumes/999/extract")
    assert response.status_code == 404


def teardown_module():
    upload_dir = Path(get_settings().resume_upload_dir)
    for path in upload_dir.glob("*"):
        path.unlink(missing_ok=True)

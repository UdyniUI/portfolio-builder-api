from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app.config import get_settings
from app.database.connection import Base, SessionLocal, engine
from app.database.models import ResumeUpload, User
from app.main import app


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def graphql(client: TestClient, query: str) -> dict:
    response = client.post("/graphql", json={"query": query})
    assert response.status_code == 200
    payload = response.json()
    assert "errors" not in payload, payload.get("errors")
    return payload["data"]


def create_user() -> int:
    with SessionLocal() as db:
        user = User(
            auth0_id="local-test-user", email="local@example.com", first_name="Local"
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id


def docx_bytes() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<document />")
    return buffer.getvalue()


def test_health_endpoints():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

        data = graphql(client, "{ health }")
        assert data["health"] == "PortfolioOS API is healthy"


def test_portfolio_create_edit_publish_flow():
    user_id = create_user()

    with TestClient(app) as client:
        created = graphql(
            client,
            f"""mutation {{
              createPortfolio(userId: {user_id}, title: "Local Portfolio", slug: "local-portfolio") {{
                success message data
              }}
            }}""",
        )["createPortfolio"]
        assert created["success"] is True

        saved = graphql(
            client,
            """mutation {
              updatePortfolioData(
                portfolioId: 1,
                sectionKey: "hero",
                content: "{\\\"headline\\\": \\\"Hello\\\"}"
              ) { success message }
            }""",
        )["updatePortfolioData"]
        assert saved["success"] is True

        published = graphql(
            client,
            "mutation { publishPortfolio(portfolioId: 1) { success message } }",
        )["publishPortfolio"]
        assert published["success"] is True

        portfolio = graphql(
            client,
            """{
              getPortfolio(slug: "local-portfolio") { title slug status updatedAt }
              getPortfolioData(portfolioId: 1) { sectionKey content orderIndex }
            }""",
        )
        assert portfolio["getPortfolio"]["status"] == "published"
        assert portfolio["getPortfolio"]["updatedAt"] is not None
        assert portfolio["getPortfolioData"][0]["sectionKey"] == "hero"


def test_duplicate_slug_returns_a_domain_error():
    user_id = create_user()

    with TestClient(app) as client:
        mutation = f"""mutation {{
          createPortfolio(userId: {user_id}, title: "First", slug: "duplicate") {{ success }}
        }}"""
        assert graphql(client, mutation)["createPortfolio"]["success"] is True

        duplicate = graphql(client, mutation)["createPortfolio"]
        assert duplicate["success"] is False


def test_pdf_upload_is_stored_and_recorded_for_the_local_user():
    content = b"%PDF-1.7\nPortfolioOS local test resume\n%%EOF"

    with TestClient(app) as client:
        response = client.post(
            "/upload",
            files={"file": ("../Udayani Resume.PDF", content, "application/pdf")},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["original_filename"] == "Udayani Resume.PDF"
    assert payload["content_type"] == "application/pdf"
    assert payload["size_bytes"] == len(content)
    assert len(payload["sha256"]) == 64
    assert payload["extraction_status"] == "pending"

    with SessionLocal() as db:
        upload = db.get(ResumeUpload, payload["id"])
        assert upload is not None
        assert upload.original_filename == "Udayani Resume.PDF"
        assert upload.file_url.startswith("local://resumes/")
        assert upload.user.auth0_id == "local-dev-user"

        stored_filename = upload.file_url.removeprefix("local://resumes/")
        stored_path = Path(get_settings().resume_upload_dir) / stored_filename
        assert stored_path.read_bytes() == content


def test_docx_upload_accepts_a_real_docx_container():
    content = docx_bytes()

    with TestClient(app) as client:
        response = client.post(
            "/upload",
            files={
                "file": (
                    "resume.docx",
                    content,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )

    assert response.status_code == 201
    assert response.json()["original_filename"] == "resume.docx"


def test_upload_rejects_unsupported_invalid_and_empty_files():
    cases = [
        ("resume.txt", b"plain text", "text/plain", 415),
        ("resume.pdf", b"not a pdf", "application/pdf", 400),
        ("resume.docx", b"not a zip", "application/zip", 400),
        ("resume.pdf", b"", "application/pdf", 400),
    ]

    with TestClient(app) as client:
        for filename, content, content_type, expected_status in cases:
            response = client.post(
                "/upload", files={"file": (filename, content, content_type)}
            )
            assert response.status_code == expected_status

    with SessionLocal() as db:
        assert db.query(ResumeUpload).count() == 0


def test_upload_rejects_files_over_ten_megabytes():
    oversized_pdf = b"%PDF-" + b"0" * (10 * 1024 * 1024)

    with TestClient(app) as client:
        response = client.post(
            "/upload",
            files={"file": ("large.pdf", oversized_pdf, "application/pdf")},
        )

    assert response.status_code == 413
    with SessionLocal() as db:
        assert db.query(ResumeUpload).count() == 0

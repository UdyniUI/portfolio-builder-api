# PortfolioOS API

FastAPI and Strawberry GraphQL backend for PortfolioOS.

## Local development

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env`, then start PostgreSQL and Redis from the sibling
`portfolio-builder-infra` repository. Run the API with:

```bash
uvicorn app.main:app --reload
```

The REST health endpoint is `http://localhost:8000/health`; GraphQL is available at
`http://localhost:8000/graphql`.

During local development, upload a PDF or DOCX résumé (maximum 10 MB) with:

```bash
curl -F "file=@resume.pdf" http://localhost:8000/upload
```

The file is stored under `data/uploads/resumes`, which is ignored by Git. PostgreSQL
stores the internal file reference, original filename, local development user, and
extraction status. Production uploads remain disabled until authentication and object
storage are connected.

Extract and structure a stored résumé with:

```bash
curl -X POST http://localhost:8000/resumes/1/extract
curl http://localhost:8000/resumes/1
```

The local deterministic extractor reads selectable PDF or DOCX text, separates profile,
summary, experience, education, skills, and projects, and records review warnings without
generating missing facts. Corrected `extracted_data` can be persisted with
`PUT /resumes/{id}/extracted-data`.

Generate or refresh an unpublished portfolio draft from the reviewed data with:

```bash
curl -X POST http://localhost:8000/resumes/1/portfolio
```

The endpoint is idempotent per résumé. It maps the reviewed channels into ordered
portfolio sections, stores them in PostgreSQL, and applies the local `Night Shift`
design system with the `Career Narrative` wireframe. It never publishes the draft.

For an existing PostgreSQL development volume created before the `processing` status was
added, apply the one-time migration before restarting the API:

```bash
psql "$DATABASE_URL" -f scripts/migrate_resume_status.sql
psql "$DATABASE_URL" -f scripts/migrate_portfolio_source.sql
```

## Tests

Tests use an isolated SQLite database and do not require Docker. They cover PDF/DOCX
extraction, failure and retry behavior, correction persistence, and idempotent draft
generation:

```bash
pytest
```

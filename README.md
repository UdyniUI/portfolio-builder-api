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
summary, experience, education, and skills, and records review warnings without generating
missing facts. A dedicated Projects heading is optional because structured Experience roles
are the portfolio's primary project case studies. Corrected `extracted_data` can be persisted with
`PUT /resumes/{id}/extracted-data`.

The draft generator converts reviewed Experience text into individual role case studies
when each entry follows this shape:

```text
Lead Product Designer — Northstar Labs
January 2023 – Present
Overview: Led the workflow platform redesign.
- Built a reusable design system for four product teams.
Impact: Reduced portfolio setup time by 40%.
Skills: Product strategy, Design systems, Accessibility
```

`Role – Company`, `Role | Company`, `Role | Company | Dates`, and `Role at Company` are
also accepted. Separate lines can use `Role:`, `Company:`, and `Dates:` prefixes. Unprefixed
lines inside a recognized role remain visible as responsibilities; only explicitly labeled
impact and skills are classified as outcomes and skill tags. Unrecognized text remains in
the raw fallback instead of producing a made-up role title.

Generate or refresh an unpublished portfolio draft from the reviewed data with:

```bash
curl -X POST http://localhost:8000/resumes/1/portfolio
```

The endpoint is idempotent per résumé. It maps the reviewed channels into ordered
portfolio sections, stores them in PostgreSQL, and applies the local `Night Shift`
design system with the `Executive Brief` wireframe. It never publishes the draft.

Generation also stores a canonical portfolio content model separate from rendered section
blobs. Each field records its provenance, résumé source reference, confidence, approval state,
importance, and readiness. Role stories remain canonical even when the selected wireframe can
only display a subset. Section rows are derived from this model for the current renderer.

Edit portfolio-specific copy or approve featured roles without changing the reviewed résumé:

```bash
curl -X PUT http://localhost:8000/portfolios/1/content \
  -H 'Content-Type: application/json' \
  -d '{"fields":[{"field_id":"identity.headline","value":"Designing evidence-led workflow products."}],"featured_role_ids":["role-1","role-3"]}'
```

The returned draft includes wireframe-specific readiness and a contextual gap queue. Missing
outcomes remain explicit gaps; PortfolioOS never generates unsupported metrics or claims.

Optional section visibility is part of canonical portfolio content. Identity and experience
remain required:

```bash
curl -X PUT http://localhost:8000/portfolios/1/content \
  -H 'Content-Type: application/json' \
  -d '{"section_visibility":{"about":false,"contact":true}}'
```

After final review, commit the current revision as one self-contained configured draft:

```bash
curl -X POST http://localhost:8000/portfolios/1/commit \
  -H 'Content-Type: application/json' \
  -d '{"expected_revision":4}'
```

The snapshot contains the resolved design, wireframe contract, canonical content, materialized
sections, readiness, and commit revision. A stale expected revision returns `409`; blocking
content gaps also prevent commit. Any later content, design, or wireframe edit increments the
revision, removes the older snapshot, and returns the portfolio to `editing`. Commit never
publishes or deploys the portfolio.

The local Output stage can list and persist appearance choices with:

```bash
curl http://localhost:8000/portfolio-options
curl -X PUT http://localhost:8000/portfolios/1/appearance \
  -H 'Content-Type: application/json' \
  -d '{"design_system_id": 2, "template_id": 2}'
```

Changing the wireframe changes the returned section order without rewriting stored résumé
content. Custom `DESIGN.md` input uses a two-step boundary: first interpret supported YAML
frontmatter, then explicitly apply it as a private design owned by the local development
user.

Public design systems are immutable starters. The visual editor first creates a private clone,
then stores only supported color and typography overrides against that starter. The resolved
draft returned by the API includes inherited values for live preview, while the public catalog
row remains unchanged. Developer Console is included as a dark, high-contrast preset.

```bash
curl -X POST http://localhost:8000/portfolios/1/design-system/clone
curl -X PUT http://localhost:8000/portfolios/1/design-system \
  -H 'Content-Type: application/json' \
  -d '{"name":"My system","colors":{"primary":"#78FF9C"},"typography":{"heading":"JetBrains Mono, ui-monospace, monospace"}}'
```

```bash
curl -X POST http://localhost:8000/portfolios/1/design-md/interpret \
  -H 'Content-Type: application/json' \
  -d '{"markdown":"---\nname: My design\ncolors:\n  primary: '\''#D8FF5F'\''\n---"}'
curl -X POST http://localhost:8000/portfolios/1/design-md \
  -H 'Content-Type: application/json' \
  -d '{"markdown":"---\nname: My design\ncolors:\n  primary: '\''#D8FF5F'\''\n---"}'
```

Only six-digit hex colors and safe font-family strings are converted into tokens. Missing
roles retain compatible current-preview values, and prose below the frontmatter is stored
but reported as unsupported rather than silently applied.

Wireframe interpretation uses the OpenAI Responses API. Set `OPENAI_API_KEY` in the shell
that starts Docker (or in the infrastructure `.env`) and optionally override
`OPENAI_WIREFRAME_MODEL`; the default is `gpt-4o-mini`. The Output stage accepts one desktop
PNG/JPG/single-page PDF up to 10 MB and an optional mobile reference. Interpretation does
not change the draft. After review and approval, the constrained layout is stored as a
private wireframe for that portfolio; source images are not retained.

For an existing PostgreSQL development volume created before the `processing` status was
added, apply the one-time migration before restarting the API:

```bash
psql "$DATABASE_URL" -f scripts/migrate_resume_status.sql
psql "$DATABASE_URL" -f scripts/migrate_portfolio_source.sql
psql "$DATABASE_URL" -f scripts/migrate_design_customization.sql
psql "$DATABASE_URL" -f scripts/migrate_role_projects.sql
psql "$DATABASE_URL" -f scripts/migrate_wireframe_import.sql
psql "$DATABASE_URL" -f scripts/migrate_curated_wireframes.sql
psql "$DATABASE_URL" -f scripts/migrate_wireframe_contracts.sql
psql "$DATABASE_URL" -f scripts/migrate_design_clone_edit.sql
psql "$DATABASE_URL" -f scripts/migrate_developer_console_design.sql
psql "$DATABASE_URL" -f scripts/migrate_portfolio_content_model.sql
psql "$DATABASE_URL" -f scripts/migrate_portfolio_commit.sql
```

## Tests

Tests use an isolated SQLite database and do not require Docker. They cover PDF/DOCX
extraction, failure and retry behavior, correction persistence, idempotent draft
generation, appearance switching, section ordering, both approval boundaries, and versioned
configured-draft commit/invalidation:

```bash
pytest
```

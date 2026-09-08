CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    auth0_id VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    avatar_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS design_systems (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    tokens JSONB NOT NULL,
    is_public BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS wireframe_templates (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    sections JSONB NOT NULL,
    is_public BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolios (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    slug VARCHAR(255) UNIQUE NOT NULL,
    design_system_id INTEGER REFERENCES design_systems(id),
    template_id INTEGER REFERENCES wireframe_templates(id),
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    custom_domain VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_portfolio_status CHECK (status IN ('draft', 'published', 'archived'))
);

CREATE TABLE IF NOT EXISTS portfolio_data (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    section_key VARCHAR(100) NOT NULL,
    content JSONB NOT NULL,
    order_index INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_portfolio_data_section UNIQUE (portfolio_id, section_key)
);

CREATE TABLE IF NOT EXISTS resume_uploads (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    file_url TEXT NOT NULL,
    original_filename VARCHAR(255),
    extracted_data JSONB,
    extraction_status VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_resume_status CHECK (extraction_status IN ('pending', 'processing', 'completed', 'failed'))
);

ALTER TABLE portfolios
    ADD COLUMN IF NOT EXISTS resume_upload_id INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'portfolios_resume_upload_id_fkey'
    ) THEN
        ALTER TABLE portfolios
            ADD CONSTRAINT portfolios_resume_upload_id_fkey
            FOREIGN KEY (resume_upload_id) REFERENCES resume_uploads(id);
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolios_resume_upload_id
    ON portfolios(resume_upload_id)
    WHERE resume_upload_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS deployments (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    deployment_url TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'in_progress',
    logs TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_deployment_status CHECK (status IN ('in_progress', 'success', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_portfolios_user_id ON portfolios(user_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_data_portfolio_id ON portfolio_data(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_resume_uploads_user_id ON resume_uploads(user_id);
CREATE INDEX IF NOT EXISTS idx_deployments_portfolio_id ON deployments(portfolio_id);

INSERT INTO design_systems (name, slug, description, tokens, is_public)
VALUES
    (
        'Night Shift',
        'night-shift',
        'An energetic dark portfolio system with acid-lime type and cobalt structure.',
        '{"colors":{"primary":"#D8FF5F","accent":"#7887FF","ink":"#F5F7F2","paper":"#090B0F","surface":"#11151C","quiet":"#9BA5B5","line":"#293140"},"typography":{"heading":"Arial Narrow","body":"Arial","mono":"ui-monospace"}}'::jsonb,
        TRUE
    ),
    (
        'Udayani Modern',
        'udayani-modern',
        'Warm editorial portfolio system with sage and amber accents.',
        '{"colors":{"primary":"#66755b","accent":"#d69a35","ink":"#1f2520","paper":"#f7f3e8"},"typography":{"heading":"Fraunces","body":"Inter","mono":"JetBrains Mono"}}'::jsonb,
        TRUE
    ),
    (
        'Minimal Dark',
        'minimal-dark',
        'Focused dark portfolio system with restrained contrast.',
        '{"colors":{"primary":"#f4f4f5","accent":"#a1a1aa","ink":"#fafafa","paper":"#18181b"},"typography":{"heading":"Inter","body":"Inter","mono":"JetBrains Mono"}}'::jsonb,
        TRUE
    ),
    (
        'Tech Forward',
        'tech-forward',
        'High-clarity technical portfolio system with cyan accents.',
        '{"colors":{"primary":"#0891b2","accent":"#22d3ee","ink":"#0f172a","paper":"#f8fafc"},"typography":{"heading":"Inter","body":"Inter","mono":"JetBrains Mono"}}'::jsonb,
        TRUE
    )
ON CONFLICT (slug) DO NOTHING;

INSERT INTO wireframe_templates (name, slug, description, sections, is_public)
VALUES (
    'Career Narrative',
    'career-narrative',
    'Hero, about, skills, experience, projects, and contact.',
    '[{"key":"hero","label":"Hero"},{"key":"about","label":"About"},{"key":"skills","label":"Skills"},{"key":"experience","label":"Experience"},{"key":"projects","label":"Projects"},{"key":"contact","label":"Contact"}]'::jsonb,
    TRUE
)
ON CONFLICT (slug) DO NOTHING;

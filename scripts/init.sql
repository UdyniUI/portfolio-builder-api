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
    owner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    base_design_system_id INTEGER REFERENCES design_systems(id) ON DELETE SET NULL,
    token_overrides JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_markdown TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS wireframe_templates (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    sections JSONB NOT NULL,
    layout JSONB,
    is_public BOOLEAN NOT NULL DEFAULT TRUE,
    owner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    source_desktop_filename VARCHAR(255),
    source_mobile_filename VARCHAR(255),
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
    content_model JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_version INTEGER NOT NULL DEFAULT 1,
    builder_revision INTEGER NOT NULL DEFAULT 1,
    configuration_status VARCHAR(50) NOT NULL DEFAULT 'editing',
    configuration_snapshot JSONB,
    configured_at TIMESTAMPTZ,
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    custom_domain VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_portfolio_status CHECK (status IN ('draft', 'published', 'archived')),
    CONSTRAINT ck_portfolio_configuration_status CHECK (configuration_status IN ('editing', 'configured'))
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
        '{"colors":{"primary":"#5f6e54","accent":"#8a5b0a","ink":"#1f2520","paper":"#f7f3e8"},"typography":{"heading":"Fraunces","body":"Inter","mono":"JetBrains Mono"}}'::jsonb,
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
        '{"colors":{"primary":"#0e7490","accent":"#155e75","ink":"#0f172a","paper":"#f8fafc"},"typography":{"heading":"Inter","body":"Inter","mono":"JetBrains Mono"}}'::jsonb,
        TRUE
    ),
    (
        'Developer Console',
        'developer-console',
        'A terminal-informed preset with high-legibility green and cyan signals.',
        '{"colors":{"primary":"#78FF9C","accent":"#5DD8FF","ink":"#E8F5E9","paper":"#07110A","surface":"#0D1B11","quiet":"#A8C5AE","line":"#275737"},"typography":{"heading":"JetBrains Mono, ui-monospace, monospace","body":"Atkinson Hyperlegible, Arial, sans-serif","mono":"JetBrains Mono, ui-monospace, monospace"}}'::jsonb,
        TRUE
    )
ON CONFLICT (slug) DO NOTHING;

INSERT INTO wireframe_templates (name, slug, description, sections, layout, is_public)
VALUES
(
  'Executive Brief',
  'executive-brief',
  'A concise, recruiter-friendly profile built around positioning and selected career proof.',
  '[{"key":"hero","label":"Identity","width":"content","alignment":"left","emphasis":"primary","group":"identity","slots":["name","headline","location"],"required_slots":["name","headline"],"min_items":1,"max_items":1,"item_limits":{},"overflow":"show-all","fallback":"show-available"},{"key":"about","label":"Positioning","width":"content","alignment":"left","emphasis":"standard","group":"narrative","slots":["body"],"required_slots":[],"min_items":0,"max_items":1,"item_limits":{},"overflow":"condense","fallback":"collapse"},{"key":"experience","label":"Selected Proof","width":"content","alignment":"left","emphasis":"standard","group":"proof","slots":["role","company","dates","summary","highlights","outcomes"],"required_slots":["role","highlights"],"min_items":1,"max_items":2,"item_limits":{"highlights":2,"outcomes":1,"skills":0},"overflow":"rank","fallback":"raw-text"},{"key":"contact","label":"Contact","width":"content","alignment":"left","emphasis":"quiet","group":"contact","slots":["email","phone","location","links"],"required_slots":[],"min_items":0,"max_items":1,"item_limits":{"links":2},"overflow":"condense","fallback":"collapse"}]'::jsonb,
  '{"desktop":{"max_width":"narrow","columns":1,"navigation":"none"},"mobile":{"max_width":"narrow","columns":1,"navigation":"none"},"confidence":1,"detected":["Curated static starter"],"warnings":[],"unsupported":[]}'::jsonb,
  TRUE
),
(
  'Case Study Ledger',
  'case-study-ledger',
  'A project-led structure that separates context, contribution, and evidence of impact.',
  '[{"key":"hero","label":"Positioning","width":"full","alignment":"left","emphasis":"primary","group":"identity","slots":["name","headline","location"],"required_slots":["name","headline"],"min_items":1,"max_items":1,"item_limits":{},"overflow":"show-all","fallback":"show-available"},{"key":"experience","label":"Featured Work","width":"full","alignment":"left","emphasis":"primary","group":"work","slots":["role","company","dates","summary","highlights","outcomes","skills"],"required_slots":["role","highlights"],"min_items":1,"max_items":4,"item_limits":{"highlights":3,"outcomes":2,"skills":4},"overflow":"condense","fallback":"raw-text"},{"key":"skills","label":"Capability Stack","width":"wide","alignment":"left","emphasis":"standard","group":"capabilities","slots":["items"],"required_slots":[],"min_items":0,"max_items":3,"item_limits":{},"overflow":"condense","fallback":"collapse"},{"key":"projects","label":"Additional Work","width":"wide","alignment":"left","emphasis":"standard","group":"work","slots":["body"],"required_slots":[],"min_items":0,"max_items":1,"item_limits":{},"overflow":"condense","fallback":"collapse"},{"key":"contact","label":"Contact","width":"full","alignment":"left","emphasis":"quiet","group":"contact","slots":["email","phone","location","links"],"required_slots":[],"min_items":0,"max_items":1,"item_limits":{"links":3},"overflow":"condense","fallback":"collapse"}]'::jsonb,
  '{"desktop":{"max_width":"wide","columns":1,"navigation":"compact"},"mobile":{"max_width":"standard","columns":1,"navigation":"compact"},"confidence":1,"detected":["Curated static starter"],"warnings":[],"unsupported":[]}'::jsonb,
  TRUE
),
(
  'Career Atlas',
  'career-atlas',
  'A comprehensive portfolio spanning capabilities, career journey, achievements, and credentials.',
  '[{"key":"hero","label":"Identity and Proof","width":"full","alignment":"left","emphasis":"primary","group":"identity","slots":["name","headline","location","proof_facts"],"required_slots":["name","headline"],"min_items":1,"max_items":1,"item_limits":{"proof_facts":4},"overflow":"condense","fallback":"show-available"},{"key":"skills","label":"Core Competencies","width":"full","alignment":"left","emphasis":"standard","group":"capabilities","slots":["items"],"required_slots":[],"min_items":0,"max_items":4,"item_limits":{},"overflow":"condense","fallback":"collapse"},{"key":"about","label":"Featured Story","width":"wide","alignment":"left","emphasis":"standard","group":"story","slots":["body"],"required_slots":[],"min_items":0,"max_items":1,"item_limits":{},"overflow":"condense","fallback":"collapse"},{"key":"experience","label":"Professional Journey","width":"full","alignment":"left","emphasis":"primary","group":"journey","slots":["role","company","dates","summary","highlights","outcomes","skills"],"required_slots":["role"],"min_items":1,"max_items":5,"item_limits":{"highlights":3,"outcomes":2,"skills":3},"overflow":"condense","fallback":"raw-text"},{"key":"projects","label":"Achievements","width":"content","alignment":"left","emphasis":"standard","group":"proof","slots":["body"],"required_slots":[],"min_items":0,"max_items":1,"item_limits":{},"overflow":"condense","fallback":"collapse"},{"key":"education","label":"Education","width":"content","alignment":"left","emphasis":"standard","group":"credentials","slots":["body"],"required_slots":[],"min_items":0,"max_items":1,"item_limits":{},"overflow":"condense","fallback":"collapse"},{"key":"contact","label":"Contact","width":"full","alignment":"left","emphasis":"quiet","group":"contact","slots":["email","phone","location","links"],"required_slots":[],"min_items":0,"max_items":1,"item_limits":{"links":4},"overflow":"condense","fallback":"collapse"}]'::jsonb,
  '{"desktop":{"max_width":"wide","columns":2,"navigation":"inline"},"mobile":{"max_width":"standard","columns":1,"navigation":"compact"},"confidence":1,"detected":["Curated static starter"],"warnings":[],"unsupported":[]}'::jsonb,
  TRUE
)
ON CONFLICT (slug) DO NOTHING;

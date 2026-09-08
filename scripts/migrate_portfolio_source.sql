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

INSERT INTO design_systems (name, slug, description, tokens, is_public)
VALUES (
    'Night Shift',
    'night-shift',
    'An energetic dark portfolio system with acid-lime type and cobalt structure.',
    '{"colors":{"primary":"#D8FF5F","accent":"#7887FF","ink":"#F5F7F2","paper":"#090B0F","surface":"#11151C","quiet":"#9BA5B5","line":"#293140"},"typography":{"heading":"Arial Narrow","body":"Arial","mono":"ui-monospace"}}'::jsonb,
    TRUE
)
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    tokens = EXCLUDED.tokens,
    is_public = EXCLUDED.is_public,
    updated_at = CURRENT_TIMESTAMP;

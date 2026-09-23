ALTER TABLE design_systems
    ADD COLUMN IF NOT EXISTS owner_user_id INTEGER,
    ADD COLUMN IF NOT EXISTS source_markdown TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'design_systems_owner_user_id_fkey'
    ) THEN
        ALTER TABLE design_systems
            ADD CONSTRAINT design_systems_owner_user_id_fkey
            FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_design_systems_owner_user_id
    ON design_systems(owner_user_id);

UPDATE design_systems
SET tokens = jsonb_set(
        jsonb_set(tokens, '{colors,primary}', '"#5f6e54"'::jsonb, TRUE),
        '{colors,accent}',
        '"#8a5b0a"'::jsonb,
        TRUE
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE slug = 'udayani-modern';

UPDATE design_systems
SET tokens = jsonb_set(
        jsonb_set(tokens, '{colors,primary}', '"#0e7490"'::jsonb, TRUE),
        '{colors,accent}',
        '"#155e75"'::jsonb,
        TRUE
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE slug = 'tech-forward';

INSERT INTO wireframe_templates (name, slug, description, sections, is_public)
VALUES
(
  'Career Narrative',
  'career-narrative',
  'A balanced story that moves from profile to capabilities and career evidence.',
  '[{"key":"hero","label":"Hero"},{"key":"about","label":"About"},{"key":"skills","label":"Skills"},{"key":"experience","label":"Role Projects"},{"key":"education","label":"Education"},{"key":"projects","label":"Additional Work"},{"key":"contact","label":"Contact"}]'::jsonb,
  TRUE
),
(
  'Project Spotlight',
  'project-spotlight',
  'Puts experience-based role projects first, followed by supporting capabilities.',
  '[{"key":"hero","label":"Hero"},{"key":"experience","label":"Role Projects"},{"key":"skills","label":"Skills"},{"key":"about","label":"About"},{"key":"education","label":"Education"},{"key":"projects","label":"Additional Work"},{"key":"contact","label":"Contact"}]'::jsonb,
  TRUE
)
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    sections = EXCLUDED.sections,
    is_public = EXCLUDED.is_public,
    updated_at = CURRENT_TIMESTAMP;

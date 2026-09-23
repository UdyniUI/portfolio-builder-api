BEGIN;

UPDATE wireframe_templates
SET name = 'Executive Brief',
    slug = 'executive-brief',
    description = 'A concise, recruiter-friendly profile built around positioning and selected career proof.',
    sections = '[{"key":"hero","label":"Identity"},{"key":"about","label":"Positioning"},{"key":"experience","label":"Selected Proof"},{"key":"contact","label":"Contact"}]'::jsonb,
    layout = '{"desktop":{"max_width":"narrow","columns":1,"navigation":"none"},"mobile":{"max_width":"narrow","columns":1,"navigation":"none"},"confidence":1,"detected":["Curated static starter"],"warnings":[],"unsupported":[]}'::jsonb,
    updated_at = CURRENT_TIMESTAMP
WHERE slug = 'career-narrative';

UPDATE wireframe_templates
SET name = 'Case Study Ledger',
    slug = 'case-study-ledger',
    description = 'A project-led structure that separates context, contribution, and evidence of impact.',
    sections = '[{"key":"hero","label":"Positioning"},{"key":"experience","label":"Featured Work"},{"key":"skills","label":"Capability Stack"},{"key":"projects","label":"Additional Work"},{"key":"contact","label":"Contact"}]'::jsonb,
    layout = '{"desktop":{"max_width":"wide","columns":1,"navigation":"compact"},"mobile":{"max_width":"standard","columns":1,"navigation":"compact"},"confidence":1,"detected":["Curated static starter"],"warnings":[],"unsupported":[]}'::jsonb,
    updated_at = CURRENT_TIMESTAMP
WHERE slug = 'project-spotlight';

INSERT INTO wireframe_templates (name, slug, description, sections, layout, is_public)
VALUES (
  'Career Atlas',
  'career-atlas',
  'A comprehensive portfolio spanning capabilities, career journey, achievements, and credentials.',
  '[{"key":"hero","label":"Identity and Proof"},{"key":"skills","label":"Core Competencies"},{"key":"about","label":"Featured Story"},{"key":"experience","label":"Professional Journey"},{"key":"projects","label":"Achievements"},{"key":"education","label":"Education"},{"key":"contact","label":"Contact"}]'::jsonb,
  '{"desktop":{"max_width":"wide","columns":2,"navigation":"inline"},"mobile":{"max_width":"standard","columns":1,"navigation":"compact"},"confidence":1,"detected":["Curated static starter"],"warnings":[],"unsupported":[]}'::jsonb,
  TRUE
)
ON CONFLICT (slug) DO UPDATE
SET name = EXCLUDED.name,
    description = EXCLUDED.description,
    sections = EXCLUDED.sections,
    layout = EXCLUDED.layout,
    is_public = TRUE,
    updated_at = CURRENT_TIMESTAMP;

COMMIT;

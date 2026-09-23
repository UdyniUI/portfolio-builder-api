BEGIN;

UPDATE wireframe_templates
SET sections = '[{"key":"hero","label":"Hero"},{"key":"about","label":"About"},{"key":"skills","label":"Skills"},{"key":"experience","label":"Role Projects"},{"key":"education","label":"Education"},{"key":"projects","label":"Additional Work"},{"key":"contact","label":"Contact"}]'::jsonb,
    updated_at = CURRENT_TIMESTAMP
WHERE slug = 'career-narrative';

UPDATE wireframe_templates
SET description = 'Puts experience-based role projects first, followed by supporting capabilities.',
    sections = '[{"key":"hero","label":"Hero"},{"key":"experience","label":"Role Projects"},{"key":"skills","label":"Skills"},{"key":"about","label":"About"},{"key":"education","label":"Education"},{"key":"projects","label":"Additional Work"},{"key":"contact","label":"Contact"}]'::jsonb,
    updated_at = CURRENT_TIMESTAMP
WHERE slug = 'project-spotlight';

COMMIT;

INSERT INTO design_systems (name, slug, description, tokens, is_public)
VALUES (
    'Developer Console',
    'developer-console',
    'A terminal-informed preset with high-legibility green and cyan signals.',
    '{"colors":{"primary":"#78FF9C","accent":"#5DD8FF","ink":"#E8F5E9","paper":"#07110A","surface":"#0D1B11","quiet":"#A8C5AE","line":"#275737"},"typography":{"heading":"JetBrains Mono, ui-monospace, monospace","body":"Atkinson Hyperlegible, Arial, sans-serif","mono":"JetBrains Mono, ui-monospace, monospace"}}'::jsonb,
    TRUE
)
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    tokens = EXCLUDED.tokens,
    is_public = TRUE,
    updated_at = CURRENT_TIMESTAMP;

ALTER TABLE wireframe_templates
    ADD COLUMN IF NOT EXISTS layout JSONB,
    ADD COLUMN IF NOT EXISTS owner_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS source_desktop_filename VARCHAR(255),
    ADD COLUMN IF NOT EXISTS source_mobile_filename VARCHAR(255);

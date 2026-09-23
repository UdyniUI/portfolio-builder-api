BEGIN;

ALTER TABLE design_systems
    ADD COLUMN IF NOT EXISTS base_design_system_id INTEGER,
    ADD COLUMN IF NOT EXISTS token_overrides JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'design_systems_base_design_system_id_fkey'
    ) THEN
        ALTER TABLE design_systems
            ADD CONSTRAINT design_systems_base_design_system_id_fkey
            FOREIGN KEY (base_design_system_id) REFERENCES design_systems(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_design_systems_base_design_system_id
    ON design_systems(base_design_system_id);

COMMIT;

BEGIN;

ALTER TABLE portfolios
    ADD COLUMN IF NOT EXISTS builder_revision INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS configuration_status VARCHAR(50) NOT NULL DEFAULT 'editing',
    ADD COLUMN IF NOT EXISTS configuration_snapshot JSONB,
    ADD COLUMN IF NOT EXISTS configured_at TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_portfolio_configuration_status'
    ) THEN
        ALTER TABLE portfolios
            ADD CONSTRAINT ck_portfolio_configuration_status
            CHECK (configuration_status IN ('editing', 'configured'));
    END IF;
END $$;

COMMIT;

BEGIN;

ALTER TABLE resume_uploads DROP CONSTRAINT IF EXISTS ck_resume_status;
ALTER TABLE resume_uploads
    ADD CONSTRAINT ck_resume_status
    CHECK (extraction_status IN ('pending', 'processing', 'completed', 'failed'));

COMMIT;

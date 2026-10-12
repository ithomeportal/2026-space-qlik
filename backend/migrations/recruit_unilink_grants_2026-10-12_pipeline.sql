-- ⚠ TARGET DATABASE: recruit_unilink (the Jobs portal), NOT the Space hub DB.
-- Applied 2026-10-12 as avnadmin (member of recruit_app). Read-only, column-level
-- grants for /api/custom/exec-meeting-recruitment/pipeline and the Monday
-- Recruitment Status e-mail. A column the pipeline reads but is not listed here
-- fails with 42501. Idempotent: re-running is harmless.
BEGIN;
SET LOCAL ROLE recruit_app;
GRANT SELECT (id, "positionId", "stageId", "candidateId", status, "createdAt", "updatedAt", "hiredAt") ON "Application" TO spaceqlik_recruit_ro;
GRANT SELECT (id, name) ON "Stage" TO spaceqlik_recruit_ro;
GRANT SELECT ("applicationId", "toStageId", "createdAt") ON "StageTransition" TO spaceqlik_recruit_ro;
GRANT SELECT (status) ON "Offer" TO spaceqlik_recruit_ro;
GRANT SELECT (id, "firstName", "paternalLastName") ON "Candidate" TO spaceqlik_recruit_ro;
COMMIT;

-- Added 2026-10-12 (later the same day): rejection events per week / per stage.
-- ActivityLog.details carries the free-text rejection reason (internal only).
BEGIN;
SET LOCAL ROLE recruit_app;
GRANT SELECT (entity, "entityId", details, "createdAt") ON "ActivityLog" TO spaceqlik_recruit_ro;
GRANT SELECT ("fromStageId") ON "StageTransition" TO spaceqlik_recruit_ro;
COMMIT;

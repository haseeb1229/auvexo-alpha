"""Append-only nonproduction study/trial/holdout metadata; no money capability."""

from alembic import op

revision = "0004_research_ledger"
down_revision = "0003_source_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='auvexo_research') THEN
            CREATE ROLE auvexo_research NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
          END IF;
        END $$;
        ALTER TABLE data_manifest DROP CONSTRAINT data_manifest_logical_key_source_hash_key;
        CREATE UNIQUE INDEX data_manifest_source_parser ON data_manifest
          (logical_key,source_hash,(COALESCE(payload::jsonb->>'parser_version','spot.v1')));
        CREATE TABLE research_study (
          study_id text PRIMARY KEY,
          manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
          payload text NOT NULL CHECK (octet_length(payload) <= 1048576),
          registered_at timestamptz NOT NULL
        );
        CREATE TABLE research_event (
          event_id text PRIMARY KEY,
          study_id text NOT NULL REFERENCES research_study(study_id),
          kind text NOT NULL CHECK (kind IN ('HOLDOUT_OPEN')),
          scope_hash text NOT NULL UNIQUE CHECK (scope_hash ~ '^[0-9a-f]{64}$'),
          payload text NOT NULL CHECK (octet_length(payload) <= 16384),
          recorded_at timestamptz NOT NULL,
          UNIQUE(study_id,kind)
        );
        CREATE TABLE research_trial (
          study_id text NOT NULL REFERENCES research_study(study_id),
          trial_id text NOT NULL,
          phase text NOT NULL CHECK (phase IN ('TRAIN','VALIDATION','OOS','WALK_FORWARD')),
          config_hash text NOT NULL CHECK (config_hash ~ '^[0-9a-f]{64}$'),
          artifact_hash text NOT NULL CHECK (artifact_hash ~ '^[0-9a-f]{64}$'),
          artifact_bytes bigint NOT NULL CHECK (artifact_bytes BETWEEN 1 AND 67108864),
          recorded_at timestamptz NOT NULL,
          PRIMARY KEY(study_id,trial_id)
        );
        CREATE TRIGGER study_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON research_study
          FOR EACH STATEMENT EXECUTE FUNCTION refuse_foundation_mutation();
        CREATE TRIGGER trial_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON research_trial
          FOR EACH STATEMENT EXECUTE FUNCTION refuse_foundation_mutation();
        CREATE TRIGGER research_event_immutable
          BEFORE UPDATE OR DELETE OR TRUNCATE ON research_event
          FOR EACH STATEMENT EXECUTE FUNCTION refuse_foundation_mutation();
        REVOKE ALL ON research_study,research_trial,research_event FROM PUBLIC;
        GRANT SELECT,INSERT ON research_study,research_trial,research_event TO auvexo_research;
        GRANT SELECT ON alembic_version,foundation_policy TO auvexo_research;
    """)


def downgrade() -> None:
    raise RuntimeError("destructive downgrade disabled; restore isolated backup or forward-fix")

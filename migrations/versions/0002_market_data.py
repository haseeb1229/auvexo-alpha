"""Append-only data lineage with a separate non-login ingestion privilege group."""

from alembic import op

revision = "0002_market_data"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='auvexo_ingest') THEN
            CREATE ROLE auvexo_ingest NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
          END IF;
        END $$;
        CREATE TABLE data_manifest (
          dataset_version text PRIMARY KEY CHECK (dataset_version ~ '^[0-9a-f]{64}$'),
          logical_key text NOT NULL,
          source_hash text NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
          recorded_at timestamptz NOT NULL,
          supersedes text REFERENCES data_manifest(dataset_version),
          manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
          payload text NOT NULL CHECK (octet_length(payload) <= 1048576),
          UNIQUE(logical_key, source_hash)
        );
        CREATE INDEX data_manifest_key ON data_manifest(logical_key, recorded_at);
        CREATE TABLE data_event (
          event_id text PRIMARY KEY,
          feed_key text NOT NULL,
          observed_at timestamptz NOT NULL,
          payload text NOT NULL CHECK (octet_length(payload) <= 16384)
        );
        CREATE INDEX data_event_feed ON data_event(feed_key, observed_at);
        CREATE TABLE data_checkpoint (
          feed_key text NOT NULL,
          next_open timestamptz NOT NULL,
          dataset_version text NOT NULL REFERENCES data_manifest(dataset_version),
          recorded_at timestamptz NOT NULL,
          PRIMARY KEY(feed_key, next_open)
        );
        CREATE TABLE data_source_review (
          review_hash text PRIMARY KEY CHECK (review_hash ~ '^[0-9a-f]{64}$'),
          payload text NOT NULL CHECK (octet_length(payload) <= 16384)
        );
        CREATE TRIGGER manifest_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON data_manifest
          FOR EACH STATEMENT EXECUTE FUNCTION refuse_foundation_mutation();
        CREATE TRIGGER data_event_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON data_event
          FOR EACH STATEMENT EXECUTE FUNCTION refuse_foundation_mutation();
        CREATE TRIGGER checkpoint_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON data_checkpoint
          FOR EACH STATEMENT EXECUTE FUNCTION refuse_foundation_mutation();
        CREATE TRIGGER source_review_immutable BEFORE UPDATE OR DELETE
          OR TRUNCATE ON data_source_review
          FOR EACH STATEMENT EXECUTE FUNCTION refuse_foundation_mutation();
        REVOKE ALL ON data_manifest, data_event, data_checkpoint, data_source_review FROM PUBLIC;
        GRANT SELECT, INSERT ON data_manifest, data_event, data_checkpoint, data_source_review
          TO auvexo_ingest;
        GRANT SELECT ON data_manifest, data_event, data_checkpoint, data_source_review
          TO auvexo_app;
        GRANT SELECT ON foundation_policy, alembic_version TO auvexo_ingest;
    """)


def downgrade() -> None:
    raise RuntimeError("destructive downgrade disabled; restore isolated backup or forward-fix")

"""Persist provider cooldowns and raw instrument-spec evidence."""

from alembic import op

revision = "0003_source_receipts"
down_revision = "0002_market_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE data_event ADD COLUMN blocked_until timestamptz;
        CREATE INDEX data_event_cooldown ON data_event(blocked_until);
        CREATE TABLE data_spec (
          spec_hash text PRIMARY KEY CHECK (spec_hash ~ '^[0-9a-f]{64}$'),
          snapshot text NOT NULL CHECK (octet_length(snapshot) <= 16384),
          source_payload bytea NOT NULL CHECK (octet_length(source_payload) <= 2097152)
        );
        CREATE TRIGGER spec_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON data_spec
          FOR EACH STATEMENT EXECUTE FUNCTION refuse_foundation_mutation();
        REVOKE ALL ON data_spec FROM PUBLIC;
        GRANT SELECT,INSERT ON data_spec TO auvexo_ingest;
        GRANT SELECT ON data_spec TO auvexo_app;
    """)


def downgrade() -> None:
    raise RuntimeError("destructive downgrade disabled; restore isolated backup or forward-fix")

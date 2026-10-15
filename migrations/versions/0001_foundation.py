"""Foundation identity and immutable disabled policy. No broker/order tables."""

from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE foundation_policy (
            singleton_id integer PRIMARY KEY CHECK (singleton_id = 1),
            policy_version text NOT NULL CHECK (policy_version = 'phase1.disabled.v1'),
            execution_enabled boolean NOT NULL CHECK (execution_enabled = false),
            binance_live_derivatives text NOT NULL
                CHECK (binance_live_derivatives = 'BLOCKED_BY_POLICY')
        );
        INSERT INTO foundation_policy VALUES (1, 'phase1.disabled.v1', false, 'BLOCKED_BY_POLICY');
        CREATE TABLE developer_event (
            event_id uuid PRIMARY KEY,
            schema_version text NOT NULL CHECK (schema_version = '1.0'),
            event_kind text NOT NULL CHECK (event_kind IN ('DEV_CHECK', 'TEST_FIXTURE')),
            observed_at timestamptz NOT NULL,
            content_hash char(64) NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$')
        );
        CREATE FUNCTION refuse_foundation_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'foundation records are append-only'; END; $$;
        CREATE TRIGGER policy_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON foundation_policy
            FOR EACH STATEMENT EXECUTE FUNCTION refuse_foundation_mutation();
        CREATE TRIGGER event_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON developer_event
            FOR EACH STATEMENT EXECUTE FUNCTION refuse_foundation_mutation();
        REVOKE ALL ON foundation_policy, developer_event FROM PUBLIC;
        GRANT SELECT ON foundation_policy, developer_event TO auvexo_app;
        GRANT SELECT ON alembic_version TO auvexo_app;
    """)


def downgrade() -> None:
    raise RuntimeError(
        "destructive downgrade disabled; restore isolated DEV/TEST backup or forward-fix"
    )

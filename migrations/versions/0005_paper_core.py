"""Isolated virtual PAPER journal, operational projections and independent truth."""

from alembic import op

revision = "0005_paper_core"
down_revision = "0004_research_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      DO $$ BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='auvexo_paper') THEN
          CREATE ROLE auvexo_paper NOLOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS;
        END IF;
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='auvexo_paper_truth') THEN
          CREATE ROLE auvexo_paper_truth NOLOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS;
        END IF;
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='auvexo_paper_owner') THEN
          CREATE ROLE auvexo_paper_owner NOLOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS;
        END IF;
      END $$;
      CREATE TABLE paper_policy (
        content_hash text PRIMARY KEY CHECK(content_hash ~ '^[0-9a-f]{64}$'),
        payload text NOT NULL CHECK(octet_length(payload)<=1048576),
        recorded_at timestamptz NOT NULL
      );
      CREATE TABLE paper_release (LIKE paper_policy INCLUDING ALL);
      ALTER TABLE paper_release ADD CHECK (
        payload::jsonb->>'kind'='TEST_ONLY' AND
        payload::jsonb->>'fixture_namespace'='PAPER_QUALIFICATION_FIXTURE' AND
        payload::jsonb->'allowed_modes'='["PAPER"]'::jsonb AND
        payload::jsonb->>'data_use'='ENGINEERING_ONLY');
      CREATE TABLE paper_production_release (LIKE paper_policy INCLUDING ALL);
      ALTER TABLE paper_production_release ADD CHECK (
        payload::jsonb->>'kind'='RESEARCH_EVIDENCED' AND
        (payload::jsonb->>'fixture_namespace') IS NULL);
      CREATE TABLE paper_account (
        account_ref text PRIMARY KEY CHECK(account_ref LIKE 'paper.%'),
        mode text NOT NULL DEFAULT 'PAPER' CHECK(mode='PAPER'),
        payload text NOT NULL CHECK(octet_length(payload)<=1048576),
        policy_hash text NOT NULL REFERENCES paper_policy(content_hash),
        release_hash text NOT NULL REFERENCES paper_release(content_hash),
        writer_epoch bigint NOT NULL DEFAULT 0 CHECK(writer_epoch>=0),
        kill_level text NOT NULL DEFAULT 'K1' CHECK(kill_level IN ('K0','K1','K2','K3','K4')),
        reconciled boolean NOT NULL DEFAULT false,
        truth_cursor bigint NOT NULL DEFAULT 0 CHECK(truth_cursor>=0),
        version bigint NOT NULL DEFAULT 0 CHECK(version>=0)
      );
      CREATE TABLE paper_intent (
        intent_hash text PRIMARY KEY CHECK(intent_hash ~ '^[0-9a-f]{64}$'),
        account_ref text NOT NULL REFERENCES paper_account(account_ref),
        logical_key text NOT NULL,
        action text NOT NULL CHECK(action IN ('OPEN','CLOSE','CANCEL','AMEND')),
        payload text NOT NULL CHECK(octet_length(payload)<=1048576),
        recorded_at timestamptz NOT NULL,
        generated_position_ref text,
        CHECK ((payload::jsonb->>'intent_id') IS NOT NULL AND
          (payload::jsonb->>'intent_id')::uuid::text=payload::jsonb->>'intent_id'),
        CHECK (payload::jsonb->>'action'=action AND payload::jsonb->>'account_ref'=account_ref),
        CHECK ((action='OPEN' AND generated_position_ref IS NOT NULL AND
          (payload::jsonb->>'position_ref') IS NULL AND
          generated_position_ref='position.'||encode(sha256(convert_to(
            account_ref||':'||(payload::jsonb->>'intent_id'),'UTF8')),'hex')) OR
          (action<>'OPEN' AND generated_position_ref IS NULL)),
        UNIQUE(account_ref,generated_position_ref),
        UNIQUE(account_ref,logical_key,action)
      );
      CREATE UNIQUE INDEX paper_intent_account_uuid ON paper_intent
        (account_ref,((payload::jsonb->>'intent_id')::uuid));
      CREATE TABLE paper_authorization (
        authorization_id text PRIMARY KEY,
        intent_hash text NOT NULL UNIQUE REFERENCES paper_intent(intent_hash),
        content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
        payload text NOT NULL CHECK(octet_length(payload)<=1048576)
      );
      CREATE TABLE paper_reservation (
        intent_hash text PRIMARY KEY REFERENCES paper_intent(intent_hash),
        account_ref text NOT NULL REFERENCES paper_account(account_ref),
        payload text NOT NULL CHECK(octet_length(payload)<=1048576),
        active boolean NOT NULL DEFAULT true
      );
      CREATE INDEX paper_reservation_account ON paper_reservation(account_ref) WHERE active;
      CREATE TABLE paper_outbox (
        intent_hash text PRIMARY KEY REFERENCES paper_intent(intent_hash),
        account_ref text NOT NULL REFERENCES paper_account(account_ref),
        writer_epoch bigint NOT NULL CHECK(writer_epoch>=0),
        state text NOT NULL CHECK(state IN ('RESERVED','SENT_PENDING','ACKNOWLEDGED',
          'REJECTED','UNKNOWN','PARTIALLY_FILLED','FILLED','CANCELED','EXPIRED')),
        filled_quantity numeric(38,18) NOT NULL DEFAULT 0 CHECK(filled_quantity>=0),
        attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 1),
        updated_at timestamptz NOT NULL
      );
      CREATE INDEX paper_outbox_account_state ON paper_outbox(account_ref,state);
      CREATE TABLE paper_journal (
        sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        event_id text NOT NULL UNIQUE,
        account_ref text NOT NULL REFERENCES paper_account(account_ref),
        intent_hash text REFERENCES paper_intent(intent_hash),
        kind text NOT NULL,
        content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
        payload text NOT NULL CHECK(octet_length(payload)<=1048576),
        recorded_at timestamptz NOT NULL
      );
      CREATE INDEX paper_journal_account_sequence ON paper_journal(account_ref,sequence);
      CREATE TABLE paper_denial (
        event_id text PRIMARY KEY,
        account_ref text NOT NULL REFERENCES paper_account(account_ref),
        intent_hash text NOT NULL CHECK(intent_hash ~ '^[0-9a-f]{64}$'),
        content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
        payload text NOT NULL CHECK(octet_length(payload)<=1048576),
        recorded_at timestamptz NOT NULL
      );
      CREATE TABLE paper_lifecycle (
        sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        release_hash text NOT NULL REFERENCES paper_release(content_hash),
        payload text NOT NULL CHECK(octet_length(payload)<=1048576),
        content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
        recorded_at timestamptz NOT NULL
      );
      CREATE TABLE paper_production_lifecycle (
        sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        release_hash text NOT NULL REFERENCES paper_production_release(content_hash),
        payload text NOT NULL,
        content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
        recorded_at timestamptz NOT NULL
      );
      CREATE TABLE paper_truth_event (
        sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        event_id text NOT NULL UNIQUE,
        account_ref text NOT NULL CHECK(account_ref LIKE 'paper.%'),
        intent_hash text CHECK(intent_hash ~ '^[0-9a-f]{64}$'),
        kind text NOT NULL CHECK(kind IN
          ('ORDER','FILL','STATUS','EXTERNAL_POSITION','ADJUSTMENT','MARKET_MARK','RESOLUTION')),
        content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
        payload text NOT NULL CHECK(octet_length(payload)<=1048576),
        recorded_at timestamptz NOT NULL
      );
      CREATE INDEX paper_truth_account_sequence ON paper_truth_event(account_ref,sequence);
      CREATE UNIQUE INDEX paper_truth_one_order ON paper_truth_event(intent_hash)
        WHERE kind='ORDER';
      REVOKE ALL ON paper_policy,paper_release,paper_account,paper_intent,
        paper_authorization,paper_reservation,paper_outbox,paper_journal,paper_denial,
        paper_lifecycle,paper_production_release,paper_production_lifecycle,paper_truth_event
        FROM PUBLIC;
      GRANT SELECT ON paper_policy,paper_release,paper_production_release,
        paper_production_lifecycle TO auvexo_paper;
      GRANT SELECT ON paper_account,paper_lifecycle TO auvexo_paper;
      GRANT SELECT,INSERT ON paper_intent,
        paper_authorization,paper_reservation,paper_outbox,paper_journal,paper_denial
        TO auvexo_paper;
      GRANT UPDATE ON paper_account,paper_reservation,paper_outbox TO auvexo_paper;
      GRANT SELECT ON paper_truth_event,foundation_policy,alembic_version TO auvexo_paper;
      GRANT SELECT,INSERT ON paper_truth_event TO auvexo_paper_truth;
      GRANT USAGE,SELECT ON SEQUENCE paper_journal_sequence_seq,paper_lifecycle_sequence_seq
        TO auvexo_paper;
      GRANT USAGE,SELECT ON SEQUENCE paper_truth_event_sequence_seq TO auvexo_paper_truth;
      GRANT SELECT ON paper_account,paper_journal,paper_truth_event,paper_outbox,
        paper_reservation,paper_intent TO auvexo_paper_owner;
      GRANT SELECT,INSERT ON paper_policy,paper_release,paper_production_release,
        paper_production_lifecycle,paper_lifecycle TO auvexo_paper_owner;
      GRANT INSERT ON paper_account TO auvexo_paper_owner;
      GRANT UPDATE ON paper_account TO auvexo_paper_owner;
      GRANT INSERT ON paper_journal TO auvexo_paper_owner;
      GRANT USAGE,SELECT ON SEQUENCE paper_journal_sequence_seq TO auvexo_paper_owner;
      GRANT USAGE,SELECT ON SEQUENCE paper_lifecycle_sequence_seq,
        paper_production_lifecycle_sequence_seq TO auvexo_paper_owner;
      CREATE FUNCTION paper_guard_account() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF (NEW.kill_level < OLD.kill_level OR
            (NEW.policy_hash,NEW.release_hash) IS DISTINCT FROM
            (OLD.policy_hash,OLD.release_hash)) AND
            NOT pg_has_role(current_user,'auvexo_paper_owner','MEMBER') THEN
          RAISE EXCEPTION 'PAPER owner role required to relax kill or change policy';
        END IF;
        IF NEW.writer_epoch < OLD.writer_epoch OR NEW.version < OLD.version OR
           NEW.truth_cursor < OLD.truth_cursor OR NEW.account_ref <> OLD.account_ref THEN
          RAISE EXCEPTION 'PAPER projection cannot rewind';
        END IF;
        IF NEW.payload::jsonb->>'kill' <> NEW.kill_level OR
           (NEW.payload::jsonb->>'epoch')::bigint <> NEW.writer_epoch OR
           (NEW.payload::jsonb->>'reconciled')::boolean <> NEW.reconciled OR
           NEW.payload::jsonb->>'account_ref' <> NEW.account_ref THEN
          RAISE EXCEPTION 'PAPER projection binding mismatch';
        END IF;
        IF (NEW.payload::jsonb->'cash',NEW.payload::jsonb->'equity',
            NEW.payload::jsonb->'positions') IS DISTINCT FROM
           (OLD.payload::jsonb->'cash',OLD.payload::jsonb->'equity',
            OLD.payload::jsonb->'positions') AND
           NEW.truth_cursor <= OLD.truth_cursor AND
           NOT pg_has_role(current_user,'auvexo_paper_owner','MEMBER') THEN
          RAISE EXCEPTION 'PAPER balance mutation requires new independent facts';
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER paper_account_guard BEFORE UPDATE ON paper_account
        FOR EACH ROW EXECUTE FUNCTION paper_guard_account();
      CREATE FUNCTION paper_fence_truth(a text,e bigint,i text,p text,t timestamptz) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
      DECLARE current_epoch bigint; current_state text;
      BEGIN
        SELECT writer_epoch INTO current_epoch FROM public.paper_account
          WHERE account_ref=a FOR UPDATE;
        SELECT state INTO current_state FROM public.paper_outbox
          WHERE account_ref=a AND intent_hash=i;
        RETURN current_epoch=e AND current_state='SENT_PENDING' AND EXISTS(
          SELECT 1 FROM public.paper_authorization auth
          JOIN public.paper_intent intent ON intent.intent_hash=auth.intent_hash
          JOIN public.paper_account account ON account.account_ref=intent.account_ref
          WHERE auth.intent_hash=i AND intent.account_ref=a
          AND account.reconciled AND account.truth_cursor=(
            SELECT COALESCE(max(sequence),0) FROM public.paper_truth_event WHERE account_ref=a)
          AND (account.kill_level='K0' OR
               (account.kill_level IN ('K1','K2','K3') AND intent.action IN ('CLOSE','CANCEL')))
          AND auth.payload::jsonb->>'semantics'='PAPER_NONEXTERNAL'
          AND (auth.payload::jsonb->>'writer_epoch')::bigint=e
          AND (auth.payload::jsonb->>'expires_at')::timestamptz>t
          AND auth.payload::jsonb->>'policy_hash'=account.policy_hash
          AND auth.payload::jsonb->>'release_hash'=account.release_hash
          AND (intent.action<>'OPEN' OR (
            (p::jsonb->>'position_ref') IS NULL AND
            NOT EXISTS(SELECT 1 FROM jsonb_array_elements(account.payload::jsonb->'positions') pos
              WHERE pos->>'position_ref'=intent.generated_position_ref) AND
            NOT EXISTS(SELECT 1 FROM public.paper_truth_event prior
              WHERE prior.account_ref=a AND prior.kind='ORDER' AND prior.intent_hash<>i
              AND prior.payload::jsonb #>> '{data,intent_id}'=p::jsonb->>'intent_id')))
          AND (p::jsonb-'quantity')=(intent.payload::jsonb-'quantity')
          AND (p::jsonb->>'quantity')::numeric=
              (auth.payload::jsonb #>> '{exposure,quantity}')::numeric);
      END $$;
      REVOKE ALL ON FUNCTION paper_fence_truth(text,bigint,text,text,timestamptz) FROM PUBLIC;
      GRANT EXECUTE ON FUNCTION paper_fence_truth(text,bigint,text,text,timestamptz)
        TO auvexo_paper_truth;
      CREATE FUNCTION paper_lock_truth(a text) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
      BEGIN
        PERFORM 1 FROM public.paper_account WHERE account_ref=a FOR UPDATE;
        RETURN FOUND;
      END $$;
      REVOKE ALL ON FUNCTION paper_lock_truth(text) FROM PUBLIC;
      GRANT EXECUTE ON FUNCTION paper_lock_truth(text) TO auvexo_paper_truth;
    """)
    for table in (
        "paper_policy",
        "paper_release",
        "paper_intent",
        "paper_authorization",
        "paper_journal",
        "paper_denial",
        "paper_lifecycle",
        "paper_truth_event",
        "paper_production_release",
        "paper_production_lifecycle",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION refuse_foundation_mutation()"
        )


def downgrade() -> None:
    raise RuntimeError(
        "destructive downgrade disabled; restore isolated DEV/TEST backup or forward-fix"
    )

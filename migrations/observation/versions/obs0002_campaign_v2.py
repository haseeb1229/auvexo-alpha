"""Campaign v2 (ADR-032): standing resume record, v2-only starts and a stronger PASS guard."""

from alembic import op

revision = "obs0002_campaign_v2"
down_revision = "obs0001_qualification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      -- The observation feed preflight reads host-scoped provider cooldowns (main 0006).
      -- A release's single probe would need INSERT; without it a probe fails closed.
      GRANT SELECT ON data_cooldown_release,data_cooldown_probe,data_cooldown_probe_result
        TO auvexo_paper_truth;
      -- OBV2-04: the accepted DS-02 exchangeInfo parser retains the raw provider bytes.
      GRANT SELECT,INSERT ON data_spec TO auvexo_paper_truth;

      -- OBV2-01: the standing owner authority carried by one START (activation) row. Its
      -- canonical payload hashes to that row's authority_hash, names the same campaign and
      -- reviewed commit, and no service identity can insert it.
      CREATE TABLE paper_observation_standing_resume (
        activation_id text PRIMARY KEY REFERENCES paper_observation_activation,
        campaign_hash text NOT NULL REFERENCES paper_observation_campaign,
        authority_hash text NOT NULL CHECK(authority_hash ~ '^[0-9a-f]{64}$'),
        payload text NOT NULL CHECK(octet_length(payload)<=65536),
        database_name text NOT NULL DEFAULT current_database()
          CHECK(database_name ~ '^auvexo_paperobs_[a-f0-9]{20}$'),
        recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
      );
      CREATE FUNCTION observation_guard_standing_resume() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE a paper_observation_activation%ROWTYPE; p jsonb;
      BEGIN
        NEW.database_name:=current_database(); NEW.recorded_at:=clock_timestamp();
        SELECT * INTO a FROM paper_observation_activation WHERE activation_id=NEW.activation_id;
        p:=NEW.payload::jsonb;
        IF NOT FOUND OR a.campaign_hash<>NEW.campaign_hash
           OR a.database_name<>current_database()
           OR a.authority_hash<>NEW.authority_hash
           OR encode(sha256(convert_to(NEW.payload,'UTF8')),'hex')<>NEW.authority_hash
           OR p->>'campaign_hash' IS DISTINCT FROM NEW.campaign_hash
           OR p->>'reviewed_sha' IS DISTINCT FROM a.reviewed_sha
           OR p->>'scope' IS DISTINCT FROM 'WRITER_ACQUISITION_K1'
           OR (SELECT payload::jsonb->>'version' FROM paper_observation_campaign
               WHERE campaign_hash=NEW.campaign_hash) IS DISTINCT FROM 'paper.observation.v2'
        THEN
          RAISE EXCEPTION 'OBSERVATION_STANDING_AUTHORITY_BINDING_DENIED';
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER observation_standing_resume_guard
        BEFORE INSERT ON paper_observation_standing_resume
        FOR EACH ROW EXECUTE FUNCTION observation_guard_standing_resume();
      CREATE TRIGGER paper_observation_standing_resume_immutable
        BEFORE UPDATE OR DELETE OR TRUNCATE ON paper_observation_standing_resume
        FOR EACH STATEMENT EXECUTE FUNCTION refuse_foundation_mutation();
      REVOKE ALL ON paper_observation_standing_resume FROM PUBLIC;
      GRANT SELECT ON paper_observation_standing_resume
        TO auvexo_paper,auvexo_paper_truth,auvexo_paper_owner;

      -- Only campaign v2 can begin a run; v1 rows stay readable and verifiable.
      CREATE OR REPLACE FUNCTION observation_guard_run() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE t timestamptz:=clock_timestamp(); a paper_observation_activation%ROWTYPE;
      BEGIN
        NEW.started_at:=t; NEW.local_date:=(t AT TIME ZONE 'Asia/Karachi')::date;
        NEW.database_name:=current_database();
        IF (SELECT payload::jsonb->>'version' FROM paper_observation_campaign
            WHERE campaign_hash=NEW.campaign_hash) IS DISTINCT FROM 'paper.observation.v2' THEN
          RAISE EXCEPTION 'OBSERVATION_CAMPAIGN_VERSION_RETIRED';
        END IF;
        IF NEW.kind='SCHEDULED' THEN
          SELECT * INTO a FROM paper_observation_activation WHERE activation_id=NEW.activation_id;
          IF NOT FOUND OR a.campaign_hash<>NEW.campaign_hash OR a.database_name<>current_database()
             OR NEW.local_date<a.first_date OR a.activated_at>=t OR
             (t AT TIME ZONE 'UTC')::time<time '16:00:00' OR
             (t AT TIME ZONE 'UTC')::time>time '16:00:15' OR
             a.reviewed_sha<>(SELECT payload::jsonb->>'git_revision' FROM
               paper_observation_campaign WHERE campaign_hash=NEW.campaign_hash) THEN
            RAISE EXCEPTION 'OBSERVATION_START_AUTHORITY_OR_WINDOW_DENIED';
          END IF;
        ELSIF NEW.activation_id IS NOT NULL THEN
          RAISE EXCEPTION 'NON_COUNTING_ACTIVATION_FORBIDDEN';
        END IF;
        RETURN NEW;
      END $$;

      -- OBV2-12 in the database as well: a v2 PASS needs the account flat, the day's
      -- flat-boundary roll journaled and an authorization of this run in a terminal state.
      CREATE OR REPLACE FUNCTION observation_guard_receipt() RETURNS trigger
        LANGUAGE plpgsql AS $$
      DECLARE r paper_observation_run%ROWTYPE; t timestamptz:=clock_timestamp();
      BEGIN
        PERFORM pg_advisory_xact_lock(hashtextextended(NEW.run_id,20802302));
        SELECT * INTO STRICT r FROM paper_observation_run WHERE run_id=NEW.run_id;
        NEW.recorded_at:=t;
        IF (NEW.campaign_hash,NEW.local_date) IS DISTINCT FROM (r.campaign_hash,r.local_date) THEN
          RAISE EXCEPTION 'OBSERVATION_RECEIPT_RUN_BINDING_DENIED';
        END IF;
        IF r.kind<>'SCHEDULED' AND NEW.disposition<>'NON_COUNTING' THEN
          RAISE EXCEPTION 'PREFLIGHT_OR_RESTORE_CANNOT_QUALIFY';
        END IF;
        IF NEW.disposition='PASS' THEN
          IF r.database_name<>current_database() OR
             (t AT TIME ZONE 'Asia/Karachi')::date<>r.local_date OR
             (t AT TIME ZONE 'UTC')::time<time '17:00:00' OR
             (t AT TIME ZONE 'UTC')::time>time '17:00:30' OR
             EXISTS(SELECT 1 FROM paper_outbox WHERE state IN ('UNKNOWN','SENT_PENDING')) OR
             EXISTS(SELECT 1 FROM paper_account WHERE NOT reconciled OR
               (payload::jsonb->>'unknown_orders')::boolean) OR
             EXISTS(SELECT 1 FROM paper_account a WHERE a.truth_cursor<>(
               SELECT COALESCE(max(sequence),0) FROM paper_truth_event t
               WHERE t.account_ref=a.account_ref)) OR
             EXISTS(SELECT 1 FROM paper_production_release) THEN
            RAISE EXCEPTION 'OBSERVATION_FINAL_STATE_OR_WINDOW_DENIED';
          END IF;
          IF (SELECT count(*) FROM (SELECT bar_end FROM paper_observation_feed
                WHERE run_id=r.run_id GROUP BY bar_end HAVING count(DISTINCT symbol)=2) pairs)<50
             OR EXISTS(SELECT 1 FROM (SELECT symbol,count(*) n,max(bar_end)-min(bar_end) span
                FROM paper_observation_feed WHERE run_id=r.run_id GROUP BY symbol) s
                WHERE n<50 OR span<interval '50 minutes') THEN
            RAISE EXCEPTION 'OBSERVATION_SOURCE_COVERAGE_DENIED';
          END IF;
          IF (SELECT payload::jsonb->>'version' FROM paper_observation_campaign
              WHERE campaign_hash=r.campaign_hash) IS NOT DISTINCT FROM 'paper.observation.v2'
             AND (
               EXISTS(SELECT 1 FROM paper_account
                 WHERE jsonb_array_length(payload::jsonb->'positions')<>0)
               OR NOT EXISTS(SELECT 1 FROM paper_journal j WHERE j.kind='FLAT_BOUNDARY_ROLL'
                 AND (j.payload::jsonb #>> '{data,account,day_start_at}')::timestamptz
                   =(r.local_date+time '00:00') AT TIME ZONE 'UTC')
               OR NOT EXISTS(SELECT 1 FROM paper_outbox o JOIN paper_intent i
                 ON i.intent_hash=o.intent_hash
                 WHERE i.recorded_at>=r.started_at
                 AND o.state IN ('FILLED','CANCELED','EXPIRED','REJECTED'))) THEN
            RAISE EXCEPTION 'OBSERVATION_V2_FINAL_STATE_DENIED';
          END IF;
        END IF;
        RETURN NEW;
      END $$;
    """)


def downgrade() -> None:
    raise RuntimeError("destructive downgrade disabled; restore isolated observation backup")

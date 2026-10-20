"""Add immutable non-counting observation preparation and future guarded date ledger."""

from alembic import op

revision = "obs0001_qualification"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      CREATE TABLE paper_observation_campaign (
        campaign_hash text PRIMARY KEY CHECK(campaign_hash ~ '^[0-9a-f]{64}$'),
        payload text NOT NULL CHECK(octet_length(payload)<=1048576),
        database_name text NOT NULL DEFAULT current_database()
          CHECK(database_name ~ '^auvexo_paperobs_[a-f0-9]{20}$'),
        recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
      );
      CREATE UNIQUE INDEX observation_campaign_identity ON paper_observation_campaign
        ((payload::jsonb->>'campaign_id'));
      CREATE TABLE paper_observation_activation (
        activation_id text PRIMARY KEY,
        campaign_hash text NOT NULL REFERENCES paper_observation_campaign,
        reviewed_sha text NOT NULL CHECK(reviewed_sha ~ '^[0-9a-f]{40}$'),
        first_date date NOT NULL,
        task_hash text NOT NULL CHECK(task_hash ~ '^[0-9a-f]{64}$'),
        authority_hash text NOT NULL CHECK(authority_hash ~ '^[0-9a-f]{64}$'),
        database_name text NOT NULL DEFAULT current_database(),
        activated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        CHECK(first_date>(activated_at AT TIME ZONE 'Asia/Karachi')::date),
        CHECK(database_name ~ '^auvexo_paperobs_[a-f0-9]{20}$')
      );
      CREATE TABLE paper_observation_run (
        run_id text PRIMARY KEY,
        campaign_hash text NOT NULL REFERENCES paper_observation_campaign,
        kind text NOT NULL CHECK(kind IN ('PREFLIGHT','SCHEDULED','RESTORE')),
        local_date date NOT NULL,
        started_at timestamptz NOT NULL,
        activation_id text REFERENCES paper_observation_activation,
        database_name text NOT NULL DEFAULT current_database(),
        payload text NOT NULL CHECK(octet_length(payload)<=1048576)
      );
      CREATE UNIQUE INDEX observation_one_scheduled_date ON paper_observation_run
        (campaign_hash,local_date) WHERE kind='SCHEDULED';
      CREATE TABLE paper_observation_feed (
        feed_hash text PRIMARY KEY CHECK(feed_hash ~ '^[0-9a-f]{64}$'),
        run_id text NOT NULL REFERENCES paper_observation_run,
        dataset_version text NOT NULL REFERENCES data_manifest,
        symbol text NOT NULL CHECK(symbol IN ('BTCUSDT','ETHUSDT')),
        bar_end timestamptz NOT NULL,
        available_at timestamptz NOT NULL,
        payload text NOT NULL CHECK(octet_length(payload)<=1048576),
        recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        UNIQUE(run_id,symbol,bar_end),CHECK(bar_end<available_at)
      );
      CREATE TABLE paper_observation_trace (
        trace_hash text PRIMARY KEY CHECK(trace_hash ~ '^[0-9a-f]{64}$'),
        run_id text NOT NULL REFERENCES paper_observation_run,
        feed_hash text NOT NULL REFERENCES paper_observation_feed,
        payload text NOT NULL CHECK(octet_length(payload)<=1048576),
        recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
      );
      CREATE TABLE paper_observation_simulation (
        simulation_hash text PRIMARY KEY CHECK(simulation_hash ~ '^[0-9a-f]{64}$'),
        run_id text NOT NULL REFERENCES paper_observation_run,
        proposal_source_hash text NOT NULL REFERENCES paper_observation_feed(feed_hash),
        fill_source_hash text NOT NULL REFERENCES paper_observation_feed(feed_hash),
        truth_event_id text NOT NULL UNIQUE REFERENCES paper_truth_event(event_id),
        payload text NOT NULL CHECK(octet_length(payload)<=1048576),
        recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
      );
      CREATE TABLE paper_observation_receipt (
        receipt_hash text PRIMARY KEY CHECK(receipt_hash ~ '^[0-9a-f]{64}$'),
        run_id text NOT NULL UNIQUE REFERENCES paper_observation_run,
        campaign_hash text NOT NULL REFERENCES paper_observation_campaign,
        local_date date NOT NULL,
        disposition text NOT NULL CHECK(disposition IN ('PASS','INCOMPLETE','NON_COUNTING')),
        payload text NOT NULL CHECK(octet_length(payload)<=1048576),
        recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
      );
      CREATE UNIQUE INDEX observation_one_final_date ON paper_observation_receipt
        (campaign_hash,local_date) WHERE disposition<>'NON_COUNTING';
      CREATE FUNCTION observation_guard_origin() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        NEW.database_name:=current_database();
        IF TG_TABLE_NAME='paper_observation_campaign' THEN
          NEW.recorded_at:=clock_timestamp();
        ELSE
          NEW.activated_at:=clock_timestamp();
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER observation_campaign_origin BEFORE INSERT ON paper_observation_campaign
        FOR EACH ROW EXECUTE FUNCTION observation_guard_origin();
      CREATE TRIGGER observation_activation_origin BEFORE INSERT ON paper_observation_activation
        FOR EACH ROW EXECUTE FUNCTION observation_guard_origin();
      CREATE FUNCTION observation_guard_run() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE t timestamptz:=clock_timestamp(); a paper_observation_activation%ROWTYPE;
      BEGIN
        NEW.started_at:=t; NEW.local_date:=(t AT TIME ZONE 'Asia/Karachi')::date;
        NEW.database_name:=current_database();
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
      CREATE TRIGGER observation_run_guard BEFORE INSERT ON paper_observation_run
        FOR EACH ROW EXECUTE FUNCTION observation_guard_run();
      CREATE FUNCTION observation_guard_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
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
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER observation_receipt_guard BEFORE INSERT ON paper_observation_receipt
        FOR EACH ROW EXECUTE FUNCTION observation_guard_receipt();
      CREATE FUNCTION observation_guard_feed() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE r paper_observation_run%ROWTYPE; t timestamptz:=clock_timestamp();
      BEGIN
        SELECT * INTO STRICT r FROM paper_observation_run WHERE run_id=NEW.run_id;
        NEW.recorded_at:=t;
        IF NEW.payload::jsonb #>> '{candle,symbol}' IS DISTINCT FROM NEW.symbol OR
           (NEW.payload::jsonb #>> '{candle,end_at}')::timestamptz IS DISTINCT FROM NEW.bar_end OR
           (NEW.payload::jsonb #>> '{candle,availability,available_at}')::timestamptz
             IS DISTINCT FROM NEW.available_at OR
           NEW.payload::jsonb #>> '{candle,source,source_id}' IS DISTINCT FROM 'DS-02' OR
           NEW.payload::jsonb #>> '{candle,interval}' IS DISTINCT FROM '1m' OR
           NEW.available_at>t OR NEW.bar_end>t THEN
          RAISE EXCEPTION 'OBSERVATION_SOURCE_BINDING_OR_FUTURE_DENIED';
        END IF;
        IF r.kind='SCHEDULED' AND (
          NEW.bar_end<(r.local_date+time '16:00:00') AT TIME ZONE 'UTC' OR
          NEW.bar_end>=(r.local_date+time '17:00:00') AT TIME ZONE 'UTC' OR
          (NEW.payload::jsonb #>> '{candle,source,received_at}')::timestamptz<r.started_at OR
          NEW.available_at>=(r.local_date+time '17:00:00') AT TIME ZONE 'UTC') THEN
          RAISE EXCEPTION 'OBSERVATION_NO_BACKFILL_OR_OUTSIDE_WINDOW';
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER observation_feed_guard BEFORE INSERT ON paper_observation_feed
        FOR EACH ROW EXECUTE FUNCTION observation_guard_feed();
      CREATE FUNCTION observation_guard_open_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        PERFORM pg_advisory_xact_lock(hashtextextended(NEW.run_id,20802302));
        IF EXISTS(SELECT 1 FROM paper_observation_receipt WHERE run_id=NEW.run_id) THEN
          RAISE EXCEPTION 'OBSERVATION_RUN_ALREADY_CLOSED';
        END IF;
        NEW.recorded_at:=clock_timestamp();
        RETURN NEW;
      END $$;
      CREATE TRIGGER observation_feed_open BEFORE INSERT ON paper_observation_feed
        FOR EACH ROW EXECUTE FUNCTION observation_guard_open_evidence();
      CREATE TRIGGER observation_trace_open BEFORE INSERT ON paper_observation_trace
        FOR EACH ROW EXECUTE FUNCTION observation_guard_open_evidence();
      CREATE TRIGGER observation_simulation_open BEFORE INSERT ON paper_observation_simulation
        FOR EACH ROW EXECUTE FUNCTION observation_guard_open_evidence();
      REVOKE ALL ON paper_observation_campaign,paper_observation_activation,paper_observation_run,
        paper_observation_feed,paper_observation_trace,paper_observation_receipt,paper_observation_simulation,
        paper_observation_version FROM PUBLIC;
      GRANT SELECT ON paper_observation_campaign,paper_observation_activation,paper_observation_run,
        paper_observation_feed,paper_observation_trace,paper_observation_receipt,paper_observation_simulation,
        paper_observation_version TO auvexo_paper,auvexo_paper_truth,auvexo_paper_owner;
      GRANT INSERT ON paper_observation_campaign TO auvexo_paper_owner;
      GRANT INSERT ON paper_observation_run,paper_observation_trace,paper_observation_receipt
        TO auvexo_paper;
      GRANT INSERT ON paper_observation_feed,paper_observation_simulation TO auvexo_paper_truth;
      GRANT SELECT,INSERT ON data_manifest,data_event,data_checkpoint,data_source_review
        TO auvexo_paper_truth;
      GRANT SELECT ON data_manifest,data_event,data_checkpoint,data_source_review TO auvexo_paper;
    """)
    for table in ("campaign", "activation", "run", "feed", "trace", "simulation", "receipt"):
        name = "paper_observation_" + table
        op.execute(
            f"CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON {name} "
            "FOR EACH STATEMENT EXECUTE FUNCTION refuse_foundation_mutation()"
        )


def downgrade() -> None:
    raise RuntimeError("destructive downgrade disabled; restore isolated observation backup")

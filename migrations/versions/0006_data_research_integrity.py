"""Cross-source conflicts, reviewed gaps, host cooldowns and database-enforced holdouts."""

from alembic import op

revision = "0006_data_research_integrity"
down_revision = "0005_paper_core"
branch_labels = None
depends_on = None

HEX = "~ '^[0-9a-f]{64}$'"
HOSTS = "('data.binance.vision','data-api.binance.vision')"
LABEL = "~ '^[A-Za-z0-9_.:-]{1,96}$'"


def upgrade() -> None:
    op.execute(f"""
      -- D-7: archive (DS-01) against REST (DS-02) comparisons of the same bar.
      CREATE TABLE data_source_comparison (
        comparison_id text PRIMARY KEY CHECK (comparison_id {HEX}),
        instrument_id text NOT NULL
          CHECK (instrument_id IN ('binance.spot.BTCUSDT','binance.spot.ETHUSDT')),
        bar_interval text NOT NULL CHECK (bar_interval IN ('1m','1h')),
        range_start timestamptz NOT NULL,
        range_end timestamptz NOT NULL CHECK (range_end > range_start),
        matched integer NOT NULL CHECK (matched >= 0),
        conflicted integer NOT NULL CHECK (conflicted >= 0),
        archive_only integer NOT NULL CHECK (archive_only >= 0),
        rest_only integer NOT NULL CHECK (rest_only >= 0),
        recorded_at timestamptz NOT NULL,
        payload text NOT NULL CHECK (octet_length(payload) <= 1048576)
      );
      CREATE TABLE data_source_conflict (
        conflict_id text PRIMARY KEY CHECK (conflict_id {HEX}),
        comparison_id text NOT NULL REFERENCES data_source_comparison(comparison_id),
        instrument_id text NOT NULL,
        bar_interval text NOT NULL CHECK (bar_interval IN ('1m','1h')),
        open_at timestamptz NOT NULL,
        archive_version text NOT NULL REFERENCES data_manifest(dataset_version),
        archive_source_hash text NOT NULL CHECK (archive_source_hash {HEX}),
        archive_market_hash text NOT NULL CHECK (archive_market_hash {HEX}),
        rest_version text NOT NULL REFERENCES data_manifest(dataset_version),
        rest_source_hash text NOT NULL CHECK (rest_source_hash {HEX}),
        rest_market_hash text NOT NULL CHECK (rest_market_hash {HEX}),
        known_at timestamptz NOT NULL,
        recorded_at timestamptz NOT NULL CHECK (recorded_at >= known_at),
        payload text NOT NULL CHECK (octet_length(payload) <= 65536),
        CHECK (archive_version <> rest_version),
        CHECK (archive_market_hash <> rest_market_hash),
        UNIQUE (archive_version, rest_version, open_at)
      );
      CREATE INDEX data_source_conflict_bar
        ON data_source_conflict(instrument_id, bar_interval, open_at);
      CREATE FUNCTION data_guard_conflict() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF (SELECT payload::jsonb #>> '{{source,source_id}}' FROM public.data_manifest
              WHERE dataset_version=NEW.archive_version) IS DISTINCT FROM 'DS-01'
           OR (SELECT payload::jsonb #>> '{{source,source_id}}' FROM public.data_manifest
              WHERE dataset_version=NEW.rest_version) IS DISTINCT FROM 'DS-02' THEN
          RAISE EXCEPTION 'CONFLICT_SOURCES_MUST_BE_ARCHIVE_AND_REST';
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER data_source_conflict_sources BEFORE INSERT ON data_source_conflict
        FOR EACH ROW EXECUTE FUNCTION data_guard_conflict();

      -- D-8: owner-reviewed provider gaps. A gap is permanent evidence, never a repair.
      CREATE TABLE data_gap_review (
        gap_id text PRIMARY KEY CHECK (gap_id {HEX}),
        feed_key text NOT NULL CHECK (feed_key ~ '^DS-02[.](BTCUSDT|ETHUSDT)[.](1m|1h)$'),
        source_id text NOT NULL CHECK (source_id = 'DS-02'),
        instrument_id text NOT NULL
          CHECK (instrument_id IN ('binance.spot.BTCUSDT','binance.spot.ETHUSDT')),
        bar_interval text NOT NULL CHECK (bar_interval IN ('1m','1h')),
        gap_start timestamptz NOT NULL,
        gap_end timestamptz NOT NULL CHECK (gap_end > gap_start),
        reason text NOT NULL CHECK (reason = 'PROVIDER_INTERVAL_ABSENT'),
        reviewer text NOT NULL CHECK (reviewer {LABEL}),
        reviewed_at timestamptz NOT NULL,
        payload_hash text NOT NULL CHECK (payload_hash {HEX}),
        payload text NOT NULL CHECK (octet_length(payload) <= 65536),
        CHECK (encode(sha256(convert_to(payload,'UTF8')),'hex') = payload_hash),
        CHECK (feed_key = 'DS-02.' || split_part(instrument_id,'.',3) || '.' || bar_interval),
        UNIQUE (feed_key, gap_start)
      );
      CREATE TABLE data_gap_evidence (
        gap_id text NOT NULL REFERENCES data_gap_review(gap_id),
        dataset_version text NOT NULL REFERENCES data_manifest(dataset_version),
        PRIMARY KEY (gap_id, dataset_version)
      );
      CREATE FUNCTION data_guard_gap() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF EXISTS (SELECT 1 FROM public.data_gap_review g WHERE g.feed_key=NEW.feed_key
                   AND g.gap_start < NEW.gap_end AND NEW.gap_start < g.gap_end) THEN
          RAISE EXCEPTION 'OVERLAPPING_GAP_REVIEW';
        END IF;
        IF EXISTS (SELECT 1 FROM public.data_checkpoint c WHERE c.feed_key=NEW.feed_key
                   AND c.next_open > NEW.gap_start) THEN
          RAISE EXCEPTION 'GAP_BEFORE_CHECKPOINT';
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER data_gap_review_guard BEFORE INSERT ON data_gap_review
        FOR EACH ROW EXECUTE FUNCTION data_guard_gap();
      CREATE FUNCTION data_gap_repeated_evidence() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF (SELECT count(*) FROM public.data_gap_evidence WHERE gap_id=NEW.gap_id) < 2 THEN
          RAISE EXCEPTION 'GAP_EVIDENCE_NOT_REPEATED';
        END IF;
        RETURN NULL;
      END $$;
      CREATE CONSTRAINT TRIGGER data_gap_review_evidence AFTER INSERT ON data_gap_review
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION data_gap_repeated_evidence();

      -- D-11: cooldowns scoped to the provider host; owner early release allows one probe.
      ALTER TABLE data_event ADD COLUMN cooldown_host text CHECK (cooldown_host IN {HOSTS});
      ALTER TABLE data_event ADD CONSTRAINT data_event_cooldown_host_bound CHECK (
        cooldown_host IS NOT DISTINCT FROM payload::jsonb->>'cooldown_host'
        AND (cooldown_host IS NULL OR blocked_until IS NOT NULL));
      CREATE INDEX data_event_host_cooldown ON data_event(cooldown_host, blocked_until)
        WHERE blocked_until IS NOT NULL;
      CREATE INDEX data_event_observed ON data_event(observed_at);
      CREATE TABLE data_cooldown_release (
        release_id text PRIMARY KEY CHECK (release_id {HEX}),
        host text NOT NULL CHECK (host IN {HOSTS}),
        released_at timestamptz NOT NULL,
        reviewer text NOT NULL CHECK (reviewer {LABEL}),
        reason text NOT NULL CHECK (reason ~ '^[ -~]+$' AND length(reason) BETWEEN 8 AND 512),
        released_until timestamptz NOT NULL CHECK (released_until > released_at),
        payload text NOT NULL CHECK (octet_length(payload) <= 16384)
      );
      CREATE FUNCTION data_guard_release() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF NOT EXISTS (SELECT 1 FROM public.data_event e WHERE e.blocked_until > NEW.released_at
                       AND e.observed_at <= NEW.released_at
                       AND (e.cooldown_host IS NULL OR e.cooldown_host = NEW.host)) THEN
          RAISE EXCEPTION 'NO_ACTIVE_COOLDOWN';
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER data_cooldown_release_active BEFORE INSERT ON data_cooldown_release
        FOR EACH ROW EXECUTE FUNCTION data_guard_release();
      CREATE TABLE data_cooldown_probe (
        release_id text PRIMARY KEY REFERENCES data_cooldown_release(release_id),
        started_at timestamptz NOT NULL,
        probe_url text NOT NULL CHECK (octet_length(probe_url) <= 512)
      );
      CREATE TABLE data_cooldown_probe_result (
        release_id text PRIMARY KEY REFERENCES data_cooldown_probe(release_id),
        outcome text NOT NULL CHECK (outcome IN ('PASSED','FAILED')),
        reason text NOT NULL CHECK (reason ~ '^[A-Z][A-Z0-9_]{{2,63}}$'),
        recorded_at timestamptz NOT NULL
      );
    """)
    for table in (
        "data_source_comparison",
        "data_source_conflict",
        "data_gap_review",
        "data_gap_evidence",
        "data_cooldown_release",
        "data_cooldown_probe",
        "data_cooldown_probe_result",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION refuse_foundation_mutation();"
            f"REVOKE ALL ON {table} FROM PUBLIC;"
            f"GRANT SELECT,INSERT ON {table} TO auvexo_ingest;"
            f"GRANT SELECT ON {table} TO auvexo_app;"
        )
    op.execute(f"""
      -- RS-8/RS-9: the database, not only the worker, enforces the holdout gate.
      GRANT SELECT ON data_manifest, data_source_conflict TO auvexo_research;
      CREATE TABLE research_study_config (
        study_id text NOT NULL REFERENCES research_study(study_id),
        config_index integer NOT NULL CHECK (config_index BETWEEN 0 AND 11),
        config_hash text NOT NULL CHECK (config_hash {HEX}),
        family text NOT NULL
          CHECK (family IN ('NO_TRADE','PASSIVE','FIXED_RULE','BREAKOUT','MEAN_REVERSION')),
        PRIMARY KEY (study_id, config_index),
        UNIQUE (study_id, config_hash)
      );
      CREATE FUNCTION research_guard_config() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE manifest jsonb;
      BEGIN
        SELECT payload::jsonb INTO manifest FROM public.research_study
          WHERE study_id=NEW.study_id;
        IF NEW.config_index >= jsonb_array_length(manifest->'configs')
           OR manifest->'configs'->NEW.config_index->>'family' IS DISTINCT FROM NEW.family THEN
          RAISE EXCEPTION 'CONFIG_ROW_NOT_IN_MANIFEST';
        END IF;
        IF EXISTS (SELECT 1 FROM public.research_trial WHERE study_id=NEW.study_id) THEN
          RAISE EXCEPTION 'CONFIGS_FROZEN_AFTER_FIRST_TRIAL';
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER research_study_config_guard BEFORE INSERT ON research_study_config
        FOR EACH ROW EXECUTE FUNCTION research_guard_config();
      CREATE TABLE research_selection (
        study_id text PRIMARY KEY REFERENCES research_study(study_id),
        selected jsonb NOT NULL CHECK (jsonb_typeof(selected) = 'array'),
        selection_artifact text NOT NULL CHECK (selection_artifact {HEX}),
        recorded_at timestamptz NOT NULL
      );
      CREATE TABLE research_holdout_completion (
        study_id text PRIMARY KEY REFERENCES research_study(study_id),
        trials jsonb NOT NULL CHECK (jsonb_typeof(trials) = 'array'),
        completed_at timestamptz NOT NULL
      );
      CREATE TABLE research_read_receipt (
        receipt_id text PRIMARY KEY CHECK (receipt_id {HEX}),
        study_id text NOT NULL REFERENCES research_study(study_id),
        phase text NOT NULL CHECK (phase IN ('TRAIN','VALIDATION','OOS','WALK_FORWARD')),
        range_start timestamptz NOT NULL,
        range_end timestamptz NOT NULL CHECK (range_end > range_start),
        holdout_state text NOT NULL CHECK (holdout_state IN ('SEALED','OPEN','COMPLETE')),
        authorized_at timestamptz NOT NULL,
        CHECK ((phase = 'OOS') = (holdout_state <> 'SEALED'))
      );
      CREATE INDEX research_read_receipt_study ON research_read_receipt(study_id, phase);
      CREATE TABLE research_read_digest (
        receipt_id text PRIMARY KEY REFERENCES research_read_receipt(receipt_id),
        bars_digest text NOT NULL CHECK (bars_digest {HEX}),
        bar_rows integer NOT NULL CHECK (bar_rows BETWEEN 1 AND 100000),
        recorded_at timestamptz NOT NULL
      );
      CREATE FUNCTION research_holdout_state(p_study text) RETURNS text
        LANGUAGE sql STABLE SET search_path=pg_catalog,public AS $$
        SELECT CASE
          WHEN NOT EXISTS (SELECT 1 FROM public.research_event
                           WHERE study_id=p_study AND kind='HOLDOUT_OPEN') THEN 'SEALED'
          WHEN EXISTS (SELECT 1 FROM public.research_holdout_completion
                       WHERE study_id=p_study) THEN 'COMPLETE'
          ELSE 'OPEN' END
      $$;
      CREATE FUNCTION research_guard_trial() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE state text;
      BEGIN
        state := public.research_holdout_state(NEW.study_id);
        IF NOT EXISTS (SELECT 1 FROM public.research_study_config
                       WHERE study_id=NEW.study_id AND config_hash=NEW.config_hash) THEN
          RAISE EXCEPTION 'TRIAL_CONFIG_NOT_REGISTERED';
        END IF;
        IF state = 'SEALED' AND NEW.phase = 'OOS' THEN
          RAISE EXCEPTION 'HOLDOUT_NOT_OPEN';
        ELSIF state <> 'SEALED' AND NEW.phase <> 'OOS' THEN
          RAISE EXCEPTION 'DEVELOPMENT_AFTER_HOLDOUT_OPEN';
        ELSIF state = 'COMPLETE' THEN
          RAISE EXCEPTION 'HOLDOUT_ALREADY_COMPLETE';
        ELSIF state = 'OPEN' AND NOT EXISTS (
            SELECT 1 FROM public.research_selection s,
              jsonb_array_elements_text(s.selected) chosen(config_hash)
            WHERE s.study_id=NEW.study_id AND chosen.config_hash=NEW.config_hash) THEN
          RAISE EXCEPTION 'OOS_CONFIG_NOT_FROZEN';
        END IF;
        -- A trial of any phase needs a gate-authorized read of that phase for this study
        -- whose served bars were bound to a digest. Receipts come only from
        -- research_authorize_read, so no result can be filed before its data was read.
        IF NOT EXISTS (SELECT 1 FROM public.research_read_receipt r
                       JOIN public.research_read_digest d ON d.receipt_id=r.receipt_id
                       WHERE r.study_id=NEW.study_id AND r.phase=NEW.phase) THEN
          RAISE EXCEPTION 'TRIAL_WITHOUT_AUTHORIZED_READ';
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER research_trial_guard BEFORE INSERT ON research_trial
        FOR EACH ROW EXECUTE FUNCTION research_guard_trial();

      CREATE FUNCTION research_study_valid(p_study text) RETURNS text
        LANGUAGE sql STABLE SET search_path=pg_catalog,public AS $$
        SELECT CASE
          WHEN NOT EXISTS (SELECT 1 FROM public.research_study WHERE study_id=p_study)
            THEN 'UNKNOWN_STUDY'
          WHEN EXISTS (SELECT 1 FROM public.research_study WHERE study_id=p_study
            AND encode(sha256(convert_to(payload,'UTF8')),'hex') <> manifest_hash)
            THEN 'CORRUPT_STUDY'
          ELSE 'VALID' END
      $$;

      CREATE FUNCTION research_freeze_selection(p_study text, p_selected jsonb, p_artifact text)
        RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
      DECLARE families integer;
      BEGIN
        PERFORM pg_advisory_xact_lock(hashtextextended(p_study,20801404));
        IF public.research_study_valid(p_study) <> 'VALID' THEN
          RETURN public.research_study_valid(p_study);
        END IF;
        IF public.research_holdout_state(p_study) <> 'SEALED' THEN
          RETURN 'HOLDOUT_ALREADY_CONSUMED';
        END IF;
        IF EXISTS (SELECT 1 FROM public.research_selection WHERE study_id=p_study) THEN
          RETURN 'SELECTION_ALREADY_FROZEN';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM public.research_trial WHERE study_id=p_study
                       AND trial_id='selection.pre_holdout' AND phase='VALIDATION'
                       AND artifact_hash=p_artifact) THEN
          RETURN 'SELECTION_TRIAL_NOT_RECORDED';
        END IF;
        -- Selection follows the complete validation grid: every registered config has a
        -- validation result of its own (the selection record itself never counts).
        IF EXISTS (SELECT 1 FROM public.research_study_config c WHERE c.study_id=p_study
                   AND NOT EXISTS (SELECT 1 FROM public.research_trial t
                     WHERE t.study_id=p_study AND t.phase='VALIDATION'
                     AND t.trial_id<>'selection.pre_holdout'
                     AND t.config_hash=c.config_hash)) THEN
          RETURN 'VALIDATION_GRID_INCOMPLETE_SELECTION_NOT_FROZEN';
        END IF;
        IF jsonb_typeof(p_selected) <> 'array' OR jsonb_array_length(p_selected) = 0
           OR EXISTS (SELECT 1 FROM jsonb_array_elements(p_selected) item(value)
                      WHERE jsonb_typeof(item.value) <> 'string'
                      OR NOT EXISTS (SELECT 1 FROM public.research_study_config c
                        WHERE c.study_id=p_study AND c.config_hash=item.value#>>'{{}}')) THEN
          RETURN 'UNREGISTERED_SELECTION';
        END IF;
        SELECT count(DISTINCT family) INTO families FROM public.research_study_config
          WHERE study_id=p_study;
        IF jsonb_array_length(p_selected) <> families OR families <> (
            SELECT count(DISTINCT c.family) FROM public.research_study_config c
            JOIN jsonb_array_elements_text(p_selected) chosen(config_hash)
              ON c.config_hash=chosen.config_hash WHERE c.study_id=p_study) THEN
          RETURN 'SELECTION_NOT_ONE_CONFIG_PER_FAMILY';
        END IF;
        INSERT INTO public.research_selection
          VALUES (p_study, p_selected, p_artifact, clock_timestamp());
        RETURN 'FROZEN';
      END $$;

      CREATE FUNCTION research_open_holdout(p_study text, p_selected jsonb, p_event text)
        RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
      DECLARE manifest jsonb; frozen public.research_selection%ROWTYPE;
        instrument text; oos_start timestamptz; oos_end timestamptz;
      BEGIN
        PERFORM pg_advisory_xact_lock(hashtextextended(p_study,20801404));
        PERFORM pg_advisory_xact_lock(20801406);
        IF public.research_study_valid(p_study) <> 'VALID' THEN
          RETURN public.research_study_valid(p_study);
        END IF;
        IF public.research_holdout_state(p_study) <> 'SEALED' THEN
          RETURN 'HOLDOUT_ALREADY_CONSUMED';
        END IF;
        IF jsonb_typeof(p_selected) <> 'array' OR jsonb_array_length(p_selected) = 0
           OR EXISTS (SELECT 1 FROM jsonb_array_elements(p_selected) item(value)
                      WHERE jsonb_typeof(item.value) <> 'string'
                      OR NOT EXISTS (SELECT 1 FROM public.research_study_config c
                        WHERE c.study_id=p_study AND c.config_hash=item.value#>>'{{}}')) THEN
          RETURN 'UNREGISTERED_SELECTION';
        END IF;
        IF EXISTS (SELECT 1 FROM public.research_study_config c WHERE c.study_id=p_study
                   AND NOT EXISTS (SELECT 1 FROM public.research_trial t
                     WHERE t.study_id=p_study AND t.phase='VALIDATION'
                     AND t.trial_id<>'selection.pre_holdout'
                     AND t.config_hash=c.config_hash)) THEN
          RETURN 'VALIDATION_GRID_INCOMPLETE_HOLDOUT_SEALED';
        END IF;
        SELECT * INTO frozen FROM public.research_selection WHERE study_id=p_study;
        IF NOT FOUND THEN
          RETURN 'SELECTION_NOT_FROZEN_HOLDOUT_SEALED';
        END IF;
        IF frozen.selected <> p_selected THEN
          RETURN 'HOLDOUT_SELECTION_NOT_FROZEN';
        END IF;
        SELECT payload::jsonb INTO manifest FROM public.research_study WHERE study_id=p_study;
        instrument := manifest->>'instrument';
        oos_start := (manifest #>> '{{split,oos_start}}')::timestamptz;
        oos_end := (manifest #>> '{{split,oos_end}}')::timestamptz;
        IF EXISTS (SELECT 1 FROM public.research_event e
                   JOIN public.research_study s ON s.study_id=e.study_id
                   WHERE e.kind='HOLDOUT_OPEN' AND s.payload::jsonb->>'instrument'=instrument
                   AND (s.payload::jsonb #>> '{{split,oos_start}}')::timestamptz < oos_end
                   AND oos_start < (s.payload::jsonb #>> '{{split,oos_end}}')::timestamptz) THEN
          RETURN 'OVERLAPPING_HOLDOUT_ALREADY_CONSUMED';
        END IF;
        INSERT INTO public.research_event VALUES (
          p_event, p_study, 'HOLDOUT_OPEN',
          encode(sha256(convert_to('holdout-scope.v2|' || instrument || '|' ||
            (extract(epoch FROM oos_start) * 1000000)::bigint || '|' ||
            (extract(epoch FROM oos_end) * 1000000)::bigint, 'UTF8')), 'hex'),
          jsonb_build_object('selected', frozen.selected,
            'selection_artifact', frozen.selection_artifact,
            'claim', 'CONSUMED_BEFORE_READ')::text,
          clock_timestamp());
        RETURN 'OPENED';
      END $$;

      CREATE FUNCTION research_authorize_read(
        p_study text, p_phase text, p_start timestamptz, p_end timestamptz, p_receipt text)
        RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
      DECLARE manifest jsonb; state text; lower_bound timestamptz; upper_bound timestamptz;
      BEGIN
        PERFORM pg_advisory_xact_lock(hashtextextended(p_study,20801404));
        IF public.research_study_valid(p_study) <> 'VALID' THEN
          RETURN public.research_study_valid(p_study);
        END IF;
        IF p_phase IS NULL OR p_phase NOT IN ('TRAIN','VALIDATION','OOS','WALK_FORWARD') THEN
          RETURN 'UNKNOWN_RESEARCH_PHASE';
        END IF;
        state := public.research_holdout_state(p_study);
        IF (p_phase = 'OOS') <> (state <> 'SEALED') THEN
          RETURN 'HOLDOUT_NOT_OPEN_OR_DEVELOPMENT_ALREADY_CONSUMED';
        END IF;
        SELECT payload::jsonb INTO manifest FROM public.research_study WHERE study_id=p_study;
        lower_bound := (manifest #>> ARRAY['split', CASE p_phase
          WHEN 'VALIDATION' THEN 'validation_start' WHEN 'OOS' THEN 'oos_start'
          ELSE 'train_start' END])::timestamptz;
        -- Walk-forward folds are derived inside the training span only (RS-10).
        upper_bound := (manifest #>> ARRAY['split', CASE p_phase
          WHEN 'VALIDATION' THEN 'validation_end' WHEN 'OOS' THEN 'oos_end'
          ELSE 'train_end' END])::timestamptz;
        IF NOT (lower_bound <= p_start AND p_start < p_end AND p_end <= upper_bound) THEN
          RETURN 'READ_OUTSIDE_REGISTERED_SPLIT';
        END IF;
        IF p_phase <> 'OOS' AND EXISTS (
            SELECT 1 FROM public.research_study s WHERE s.study_id<>p_study
            AND s.payload::jsonb->>'instrument' = manifest->>'instrument'
            AND (s.payload::jsonb #>> '{{split,oos_start}}')::timestamptz < p_end
            AND p_start < (s.payload::jsonb #>> '{{split,oos_end}}')::timestamptz
            AND NOT EXISTS (SELECT 1 FROM public.research_event e
              WHERE e.study_id=s.study_id AND e.kind='HOLDOUT_OPEN')) THEN
          RETURN 'READ_OVERLAPS_SEALED_HOLDOUT_OF_ANOTHER_STUDY';
        END IF;
        INSERT INTO public.research_read_receipt
          VALUES (p_receipt, p_study, p_phase, p_start, p_end, state, clock_timestamp());
        RETURN 'AUTHORIZED';
      END $$;

      CREATE FUNCTION research_complete_holdout(p_study text, p_trials jsonb)
        RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
      BEGIN
        PERFORM pg_advisory_xact_lock(hashtextextended(p_study,20801404));
        IF public.research_study_valid(p_study) <> 'VALID' THEN
          RETURN public.research_study_valid(p_study);
        END IF;
        IF public.research_holdout_state(p_study) = 'SEALED' THEN
          RETURN 'HOLDOUT_NOT_OPEN';
        END IF;
        IF public.research_holdout_state(p_study) = 'COMPLETE' THEN
          RETURN 'HOLDOUT_ALREADY_COMPLETE';
        END IF;
        IF jsonb_typeof(p_trials) <> 'array' OR jsonb_array_length(p_trials) = 0
           OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(p_trials) item(trial_id)
             WHERE NOT EXISTS (SELECT 1 FROM public.research_trial t WHERE t.study_id=p_study
               AND t.trial_id=item.trial_id AND t.phase='OOS')) THEN
          RETURN 'HOLDOUT_TRIALS_MISSING';
        END IF;
        INSERT INTO public.research_holdout_completion
          VALUES (p_study, p_trials, clock_timestamp());
        RETURN 'COMPLETED';
      END $$;
    """)
    for table in (
        "research_study_config",
        "research_selection",
        "research_holdout_completion",
        "research_read_receipt",
        "research_read_digest",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION refuse_foundation_mutation();"
            f"REVOKE ALL ON {table} FROM PUBLIC;"
            f"GRANT SELECT ON {table} TO auvexo_research;"
        )
    op.execute("""
      -- Selection, holdout opening, read receipts and completion only through the gates.
      REVOKE INSERT ON research_event FROM auvexo_research;
      GRANT INSERT ON research_study_config, research_read_digest TO auvexo_research;
      REVOKE ALL ON FUNCTION research_freeze_selection(text,jsonb,text) FROM PUBLIC;
      REVOKE ALL ON FUNCTION research_open_holdout(text,jsonb,text) FROM PUBLIC;
      REVOKE ALL ON FUNCTION
        research_authorize_read(text,text,timestamptz,timestamptz,text) FROM PUBLIC;
      REVOKE ALL ON FUNCTION research_complete_holdout(text,jsonb) FROM PUBLIC;
      GRANT EXECUTE ON FUNCTION research_freeze_selection(text,jsonb,text) TO auvexo_research;
      GRANT EXECUTE ON FUNCTION research_open_holdout(text,jsonb,text) TO auvexo_research;
      GRANT EXECUTE ON FUNCTION
        research_authorize_read(text,text,timestamptz,timestamptz,text) TO auvexo_research;
      GRANT EXECUTE ON FUNCTION research_complete_holdout(text,jsonb) TO auvexo_research;
    """)


def downgrade() -> None:
    raise RuntimeError("destructive downgrade disabled; restore isolated backup or forward-fix")

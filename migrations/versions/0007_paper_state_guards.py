"""PAPER state transitions bound to the journal, truth-cursor targets and kernel uniqueness."""

from alembic import op

revision = "0007_paper_state_guards"
down_revision = "0006_data_research_integrity"
branch_labels = None
depends_on = None

# A row inserted earlier in the current top-level transaction carries this xmin. The store
# never writes PAPER state inside a savepoint, so the journal event that justifies an
# update is always visible under the same transaction identifier.
CURRENT_XID = "(pg_current_xact_id()::text::numeric % 4294967296)::text"


def upgrade() -> None:
    op.execute(f"""
      -- OBV2-04/OBV2-07: provider specification observations are independent truth facts.
      ALTER TABLE paper_truth_event DROP CONSTRAINT paper_truth_event_kind_check;
      ALTER TABLE paper_truth_event ADD CONSTRAINT paper_truth_event_kind_check CHECK (kind IN
        ('ORDER','FILL','STATUS','EXTERNAL_POSITION','ADJUSTMENT','MARKET_MARK','RESOLUTION',
         'SPEC_OBSERVATION'));

      -- P-14: the kernel refuses any reuse of a logical key, whatever the action.
      CREATE UNIQUE INDEX paper_intent_account_logical_key
        ON paper_intent(account_ref, logical_key);
      CREATE INDEX paper_journal_intent ON paper_journal(intent_hash, sequence)
        WHERE intent_hash IS NOT NULL;
      ALTER TABLE paper_reservation ADD CONSTRAINT paper_reservation_active_state
        CHECK (active = (payload::jsonb->>'state' <> 'RELEASED'));

      -- P-12/OBV2-10: every account projection change is one journaled transition, and each
      -- journal kind may change only its own fields. The journal event must be the latest
      -- for the account, written in this transaction, and carry exactly the new projection.
      CREATE FUNCTION paper_guard_account_transition() RETURNS trigger LANGUAGE plpgsql
        SET search_path=pg_catalog,public AS $$
      DECLARE
        xid text := {CURRENT_XID};
        event_kind text; envelope jsonb; fresh boolean; event_at timestamptz;
        old_p jsonb := OLD.payload::jsonb;
        new_p jsonb := NEW.payload::jsonb;
        changed text[]; allowed text[];
      BEGIN
        SELECT j.kind, j.payload::jsonb, j.xmin::text = xid, j.recorded_at
          INTO event_kind, envelope, fresh, event_at
          FROM public.paper_journal j WHERE j.account_ref=NEW.account_ref
          ORDER BY j.sequence DESC LIMIT 1;
        IF NOT FOUND OR NOT fresh OR envelope #> '{{data,account}}' IS DISTINCT FROM new_p THEN
          RAISE EXCEPTION 'PAPER_ACCOUNT_TRANSITION_UNJOURNALED';
        END IF;
        -- Intent history is re-derived from paper_intent on every read; it is not state.
        SELECT coalesce(array_agg(k.key), ARRAY[]::text[]) INTO changed
          FROM jsonb_object_keys(old_p || new_p) AS k(key)
          WHERE old_p->k.key IS DISTINCT FROM new_p->k.key
          AND k.key NOT IN ('prior_intent_ids','prior_logical_keys','recent_intent_times');
        allowed := CASE event_kind
          WHEN 'WRITER_ACQUIRED_PAUSE_NEW' THEN ARRAY['epoch','kill','reconciled']
          WHEN 'KILL_STATE' THEN ARRAY['kill','reconciled']
          WHEN 'UNKNOWN_RECONCILE_ONLY' THEN ARRAY['kill','reconciled','unknown_orders']
          WHEN 'RECONCILIATION' THEN ARRAY['snapshot_id','as_of','reconciled_at','cash',
            'equity','high_water_equity','positions','day_net_flows',
            'net_flows_since_high_water','reconciled','unknown_orders','kill']
          -- A roll first latches any loss breach of the closing day (kill raise only).
          WHEN 'UTC_DAY_ROLLOVER' THEN
            ARRAY['as_of','day_start_at','day_start_equity','day_net_flows','kill']
          WHEN 'FLAT_BOUNDARY_ROLL' THEN
            ARRAY['day_start_at','day_start_equity','day_net_flows','kill']
          WHEN 'OWNER_PAPER_RESUME' THEN ARRAY['kill']
          WHEN 'OWNER_RELEASE_PIN' THEN ARRAY['kill','reconciled']
          WHEN 'OWNER_POLICY_PIN' THEN ARRAY['kill','reconciled']
          ELSE NULL END;
        IF allowed IS NULL OR NOT changed <@ allowed THEN
          RAISE EXCEPTION 'PAPER_ACCOUNT_TRANSITION_NOT_ALLOWED';
        END IF;
        IF event_kind LIKE 'OWNER_%'
           AND NOT pg_has_role(current_user,'auvexo_paper_owner','MEMBER') THEN
          RAISE EXCEPTION 'PAPER_OWNER_TRANSITION_REQUIRES_OWNER';
        END IF;
        IF NEW.kill_level < OLD.kill_level AND event_kind <> 'OWNER_PAPER_RESUME' THEN
          RAISE EXCEPTION 'PAPER_KILL_LOWERED_OUTSIDE_OWNER_RESUME';
        END IF;
        IF NEW.reconciled AND NOT OLD.reconciled AND event_kind <> 'RECONCILIATION' THEN
          RAISE EXCEPTION 'PAPER_RECONCILED_OUTSIDE_RECONCILIATION';
        END IF;
        IF event_kind = 'WRITER_ACQUIRED_PAUSE_NEW' AND (
             NEW.writer_epoch <> OLD.writer_epoch + 1 OR NEW.reconciled
             OR NEW.kill_level = 'K0') THEN
          RAISE EXCEPTION 'PAPER_WRITER_TRANSITION_INVALID';
        END IF;
        IF event_kind = 'UNKNOWN_RECONCILE_ONLY'
           AND NOT ((new_p->>'unknown_orders')::boolean AND NOT NEW.reconciled
                    AND NEW.kill_level <> 'K0') THEN
          RAISE EXCEPTION 'PAPER_UNKNOWN_TRANSITION_INVALID';
        END IF;
        -- A roll starts only a UTC day that has begun on the database clock. Its journaled
        -- instant, from which replay derives the day, lies inside that day and not ahead
        -- of the database clock, so no session can pre-roll to a later midnight and reset
        -- the daily-loss baseline early.
        IF event_kind IN ('UTC_DAY_ROLLOVER','FLAT_BOUNDARY_ROLL') AND NOT (
             (new_p->>'day_start_at')::timestamptz > (old_p->>'day_start_at')::timestamptz
             AND new_p->>'day_start_at' LIKE '%T00:00:00.000000Z'
             AND (new_p->>'day_start_at')::timestamptz <= clock_timestamp()
             AND event_at >= (new_p->>'day_start_at')::timestamptz
             AND event_at < (new_p->>'day_start_at')::timestamptz + interval '1 day'
             AND event_at <= clock_timestamp() + interval '1 second'
             AND (new_p->>'day_start_equity')::numeric = (old_p->>'equity')::numeric
             AND (new_p->>'day_net_flows')::numeric = 0) THEN
          RAISE EXCEPTION 'PAPER_DAY_ROLL_INVALID';
        END IF;
        IF event_kind = 'FLAT_BOUNDARY_ROLL' AND (
             jsonb_array_length(new_p->'positions') <> 0 OR NOT NEW.reconciled
             OR (new_p->>'unknown_orders')::boolean) THEN
          RAISE EXCEPTION 'PAPER_FLAT_ROLL_REQUIRES_FLAT_RECONCILED_ACCOUNT';
        END IF;
        -- The cursor names an existing truth event and moves only with a reconciliation.
        IF NEW.truth_cursor <> OLD.truth_cursor AND NOT EXISTS (
             SELECT 1 FROM public.paper_truth_event t
             WHERE t.account_ref=NEW.account_ref AND t.sequence=NEW.truth_cursor) THEN
          RAISE EXCEPTION 'PAPER_TRUTH_CURSOR_TARGET_UNKNOWN';
        END IF;
        IF (NEW.truth_cursor <> OLD.truth_cursor OR event_kind = 'RECONCILIATION') AND (
             event_kind <> 'RECONCILIATION'
             OR NEW.truth_cursor <> (envelope #>> '{{data,truth_cursor}}')::bigint) THEN
          RAISE EXCEPTION 'PAPER_TRUTH_CURSOR_UNJOURNALED';
        END IF;
        IF NEW.policy_hash <> OLD.policy_hash AND (event_kind <> 'OWNER_POLICY_PIN'
             OR NEW.policy_hash <> envelope #>> '{{data,policy_hash}}') THEN
          RAISE EXCEPTION 'PAPER_POLICY_PIN_UNJOURNALED';
        END IF;
        IF NEW.release_hash <> OLD.release_hash AND (event_kind <> 'OWNER_RELEASE_PIN'
             OR NEW.release_hash <> envelope #>> '{{data,release_hash}}') THEN
          RAISE EXCEPTION 'PAPER_RELEASE_PIN_UNJOURNALED';
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER paper_account_transition_guard BEFORE UPDATE ON paper_account
        FOR EACH ROW EXECUTE FUNCTION paper_guard_account_transition();

      -- Order state, fill quantity and attempts move only with their journaled order event.
      CREATE FUNCTION paper_guard_outbox_transition() RETURNS trigger LANGUAGE plpgsql
        SET search_path=pg_catalog,public AS $$
      DECLARE
        xid text := {CURRENT_XID};
        event_kind text; envelope jsonb;
      BEGIN
        IF (NEW.intent_hash, NEW.account_ref, NEW.writer_epoch)
             IS DISTINCT FROM (OLD.intent_hash, OLD.account_ref, OLD.writer_epoch)
           OR NEW.attempts < OLD.attempts
           OR (NEW.state = 'RESERVED' AND OLD.state <> 'RESERVED') THEN
          RAISE EXCEPTION 'PAPER_OUTBOX_IDENTITY_OR_REWIND';
        END IF;
        IF (NEW.state, NEW.filled_quantity, NEW.attempts)
             IS NOT DISTINCT FROM (OLD.state, OLD.filled_quantity, OLD.attempts) THEN
          RETURN NEW;
        END IF;
        SELECT j.kind, j.payload::jsonb INTO event_kind, envelope
          FROM public.paper_journal j
          WHERE j.intent_hash=NEW.intent_hash AND j.account_ref=NEW.account_ref
          AND j.xmin::text = xid ORDER BY j.sequence DESC LIMIT 1;
        IF NOT FOUND
           OR event_kind NOT IN ('DISPATCH_ATTEMPT','UNKNOWN_RECONCILE_ONLY','RECONCILED_ORDER')
           OR (event_kind = 'DISPATCH_ATTEMPT' AND NOT (
                 OLD.state = 'RESERVED' AND NEW.state = 'SENT_PENDING' AND NEW.attempts = 1
                 AND NEW.filled_quantity = OLD.filled_quantity))
           OR (event_kind = 'UNKNOWN_RECONCILE_ONLY' AND NOT (
                 NEW.state = 'UNKNOWN' AND NEW.attempts = OLD.attempts
                 AND NEW.filled_quantity = OLD.filled_quantity))
           OR (event_kind = 'RECONCILED_ORDER' AND NOT (
                 NEW.state = envelope #>> '{{data,state}}' AND NEW.attempts = OLD.attempts
                 AND NEW.filled_quantity = (envelope #>> '{{data,filled_quantity}}')::numeric))
        THEN
          RAISE EXCEPTION 'PAPER_OUTBOX_TRANSITION_UNJOURNALED';
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER paper_outbox_transition_guard BEFORE UPDATE ON paper_outbox
        FOR EACH ROW EXECUTE FUNCTION paper_guard_outbox_transition();

      -- A reservation's capacity changes only with the journal event that carries it.
      CREATE FUNCTION paper_guard_reservation_transition() RETURNS trigger LANGUAGE plpgsql
        SET search_path=pg_catalog,public AS $$
      DECLARE
        xid text := {CURRENT_XID};
      BEGIN
        IF (NEW.intent_hash, NEW.account_ref) IS DISTINCT FROM (OLD.intent_hash, OLD.account_ref)
        THEN
          RAISE EXCEPTION 'PAPER_RESERVATION_IDENTITY_CHANGED';
        END IF;
        IF (NEW.payload, NEW.active) IS NOT DISTINCT FROM (OLD.payload, OLD.active) THEN
          RETURN NEW;
        END IF;
        IF NOT EXISTS (
             SELECT 1 FROM public.paper_journal j
             WHERE j.intent_hash=NEW.intent_hash AND j.account_ref=NEW.account_ref
             AND j.xmin::text = xid
             AND j.kind IN ('UNKNOWN_RECONCILE_ONLY','RECONCILED_ORDER')
             AND j.payload::jsonb #> '{{data,reservation}}' = NEW.payload::jsonb) THEN
          RAISE EXCEPTION 'PAPER_RESERVATION_TRANSITION_UNJOURNALED';
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER paper_reservation_transition_guard BEFORE UPDATE ON paper_reservation
        FOR EACH ROW EXECUTE FUNCTION paper_guard_reservation_transition();
    """)


def downgrade() -> None:
    raise RuntimeError(
        "destructive downgrade disabled; restore isolated DEV/TEST backup or forward-fix"
    )

"""Real PostgreSQL: archive/REST conflicts, reviewed gaps, host cooldowns and bounded
reports beyond 10,000 rows. Each test has its own generated database (DB-2).

Synthetic fixtures only, never source qualification evidence.
"""

import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pg_fixtures import engine_for, generated_database, writer_engine
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from test_data_gates import qualification, receipts
from test_data_parser import archive, row

from auvexo_alpha.domain.market_data import (
    ARCHIVE_HOST,
    REST_HOST,
    GapObservation,
    GapReview,
    IngestionEvent,
)
from auvexo_alpha.infrastructure import data_store
from auvexo_alpha.infrastructure.data_store import DataStore, file_hash
from auvexo_alpha.infrastructure.source_registry import identity, rights
from auvexo_alpha.infrastructure.spot_parser import EPOCH, parse_archive, parse_rest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from verify_data_recovery import IMMUTABLE, TABLES  # noqa: E402

pytestmark = pytest.mark.integration

HOUR = timedelta(hours=1)
MINUTE = timedelta(minutes=1)
DAY = datetime(2024, 12, 31, tzinfo=UTC)
RECEIVED = datetime(2026, 10, 20, 9, tzinfo=UTC)


@pytest.fixture
def store(tmp_path):
    with generated_database() as name:
        engine = writer_engine(name)
        try:
            yield DataStore(engine, tmp_path / "data", tmp_path)
        finally:
            engine.dispose()


def publish_archive(store, prices=None):
    prices = prices or {}
    rows = [row(DAY + h * HOUR, price=prices.get(h, "100")) for h in range(24)]
    raw, checksum = archive(rows)
    url = "https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1h/BTCUSDT-1h-2024-12-31.zip"
    bars, report = parse_archive(
        raw,
        checksum,
        "BTCUSDT-1h-2024-12-31.zip",
        "BTCUSDT",
        "1h",
        DAY,
        DAY + 24 * HOUR,
        RECEIVED,
        url,
    )
    return store.publish(
        bars,
        report,
        identity("DS-01", RECEIVED),
        rights("DS-01", RECEIVED),
        "DS-01.BTCUSDT.1h.2024-12-31",
        url,
        raw,
        RECEIVED,
        "synthetic-test",
    )


def publish_rest(store, start, end, received, interval="1h", skip=(), prices=None, checkpoint=None):
    step = HOUR if interval == "1h" else MINUTE
    prices = prices or {}
    rows, opened = [], start
    while opened < end:
        if opened not in skip:
            values = row(opened, price=prices.get(opened, "100"))
            values[6] = str((opened + step - EPOCH) // timedelta(milliseconds=1) - 1)
            rows.append(values)
        opened += step
    raw = json.dumps(rows).encode()
    begin_ms = (start - EPOCH) // timedelta(milliseconds=1)
    end_ms = (end - EPOCH) // timedelta(milliseconds=1) - 1
    url = (
        "https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT"
        f"&interval={interval}&startTime={begin_ms}&endTime={end_ms}&limit=1000"
    )
    bars, report = parse_rest(raw, "BTCUSDT", interval, start, end, received, url)
    return store.publish(
        bars,
        report,
        identity("DS-02", received),
        rights("DS-02", received),
        f"DS-02.BTCUSDT.{interval}.{begin_ms}.{end_ms}",
        url,
        raw,
        received,
        "synthetic-test",
        checkpoint,
    )


def count(store, table):
    with store.engine.connect() as conn:
        return conn.scalar(text(f"SELECT count(*) FROM {table}"))


def test_archive_and_rest_conflicts_are_recorded_once_and_nothing_is_rewritten(store):
    archived = publish_archive(store)
    rest = publish_rest(
        store, DAY, DAY + 24 * HOUR, RECEIVED + MINUTE, prices={DAY + 5 * HOUR: "101"}
    )
    before = {m.dataset_version: file_hash(store.path(m)) for m in (archived, rest)}
    comparison, conflicts = store.compare_sources(
        "binance.spot.BTCUSDT", "1h", DAY, DAY + 24 * HOUR, RECEIVED + HOUR
    )
    assert (comparison.matched, len(conflicts)) == (23, 1)
    (conflict,) = conflicts
    assert conflict.open_at == DAY + 5 * HOUR
    assert (conflict.archive_version, conflict.rest_version) == (
        archived.dataset_version,
        rest.dataset_version,
    )
    # Re-running the same comparison appends nothing; stored bars and manifests are untouched.
    again, _ = store.compare_sources(
        "binance.spot.BTCUSDT", "1h", DAY, DAY + 24 * HOUR, RECEIVED + 2 * HOUR
    )
    assert again == comparison
    assert (count(store, "data_source_comparison"), count(store, "data_source_conflict")) == (1, 1)
    assert {m.dataset_version: file_hash(store.path(m)) for m in (archived, rest)} == before
    assert len(store.manifests()) == 2
    for manifest in (archived, rest):
        store.verify(manifest)
    assert store.conflicts("binance.spot.BTCUSDT", "1h", DAY, DAY + 24 * HOUR) == [conflict]
    # The database refuses a "conflict" that does not pair an archive with a REST bar.
    with pytest.raises(DBAPIError, match="CONFLICT_SOURCES_MUST_BE_ARCHIVE_AND_REST"):
        with store.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO data_source_conflict SELECT md5(conflict_id)||md5(conflict_id),"
                    "comparison_id,instrument_id,bar_interval,open_at,rest_version,"
                    "archive_source_hash,archive_market_hash,archive_version,rest_source_hash,"
                    "rest_market_hash,known_at,recorded_at,payload FROM data_source_conflict"
                )
            )
    for statement in (
        "DELETE FROM data_source_conflict",
        "UPDATE data_source_comparison SET matched=0",
    ):
        with pytest.raises(DBAPIError), store.engine.begin() as conn:
            conn.execute(text(statement))


def gap_setup(store):
    """A checkpointed 1h feed at T, then two distinct responses that omit T+1h."""
    t = datetime(2026, 10, 19, 10, tzinfo=UTC)
    publish_rest(store, t - 2 * HOUR, t, t + MINUTE, checkpoint="DS-02.BTCUSDT.1h")
    first = publish_rest(store, t, t + 3 * HOUR, t + 3 * HOUR + MINUTE, skip={t + HOUR})
    second = publish_rest(store, t, t + 4 * HOUR, t + 4 * HOUR + MINUTE, skip={t + HOUR})
    assert first.coverage.status == second.coverage.status == "DEGRADED"
    return t, (first, second)


def gap_review(t, evidence, reviewed_at=None):
    return GapReview(
        feed_key="DS-02.BTCUSDT.1h",
        instrument_id="binance.spot.BTCUSDT",
        interval="1h",
        gap_start=t + HOUR,
        gap_end=t + 2 * HOUR,
        evidence=tuple(
            GapObservation(
                dataset_version=m.dataset_version,
                source_hash=m.source_hash,
                received_at=m.created_at,
            )
            for m in evidence
        ),
        reviewer="owner.review",
        reviewed_at=reviewed_at or t + 5 * HOUR,
    )


def test_reviewed_gap_is_accepted_once_and_stays_visible_after_a_revision(store):
    t, evidence = gap_setup(store)
    review = gap_review(t, evidence)
    gap_id = store.record_gap(review)
    assert gap_id == review.content_hash()
    assert store.gaps(t, t + 24 * HOUR) == [review]
    assert (count(store, "data_gap_review"), count(store, "data_gap_evidence")) == (1, 2)
    with pytest.raises(ValueError, match="^OVERLAPPING_GAP_REVIEW$"):
        store.record_gap(gap_review(t, evidence, t + 6 * HOUR))
    # The provider later serves the bar (a revision). Nothing is repaired: the reviewed gap
    # remains in coverage and keeps its day out of qualification.
    revised = publish_rest(store, t + HOUR, t + 2 * HOUR, t + 7 * HOUR)
    assert revised.coverage.status == "PASS"
    assert store.gaps(t, t + 24 * HOUR) == [review]
    _, _, _, gaps = store.qualification_inputs(t.date(), days=1)
    assert gaps == [review]
    for statement in ("DELETE FROM data_gap_review", "UPDATE data_gap_review SET reviewer='x'"):
        with pytest.raises(DBAPIError), store.engine.begin() as conn:
            conn.execute(text(statement))


def test_gap_contradicted_by_any_stored_response_is_refused(store):
    t, evidence = gap_setup(store)
    publish_rest(store, t + HOUR, t + 2 * HOUR, t + 2 * HOUR + MINUTE)
    with pytest.raises(ValueError, match="^GAP_EVIDENCE_CONFLICT$"):
        store.record_gap(gap_review(t, evidence))
    assert count(store, "data_gap_review") == 0


def test_database_refuses_unrepeated_or_pre_checkpoint_gap_rows(store):
    t, (first, second) = gap_setup(store)
    review = gap_review(t, (first, second))
    payload = review.canonical_bytes().decode()
    insert = (
        "INSERT INTO data_gap_review VALUES (:i,'DS-02.BTCUSDT.1h','DS-02',"
        "'binance.spot.BTCUSDT','1h',:s,:e,'PROVIDER_INTERVAL_ABSENT','owner.review',:t,:i,:p)"
    )
    values = {"i": review.content_hash(), "s": t + HOUR, "e": t + 2 * HOUR, "t": t, "p": payload}
    with pytest.raises(DBAPIError, match="GAP_EVIDENCE_NOT_REPEATED"):
        with store.engine.begin() as conn:
            conn.execute(text(insert), values)
            conn.execute(
                text("INSERT INTO data_gap_evidence VALUES (:i,:v)"),
                {"i": review.content_hash(), "v": first.dataset_version},
            )
    early = values | {"s": t - HOUR, "e": t}
    with pytest.raises(DBAPIError, match="GAP_BEFORE_CHECKPOINT"):
        with store.engine.begin() as conn:
            conn.execute(text(insert), early)
    with pytest.raises(ValueError, match="^GAP_BEFORE_CHECKPOINT$"):
        store.record_gap(
            gap_review(t, (first, second)).model_copy(update={"gap_start": t - HOUR, "gap_end": t})
        )
    assert count(store, "data_gap_review") == 0


def cooldown_event(event_id, host, at, seconds=3600):
    return IngestionEvent(
        event_id=event_id,
        feed_key="DS-02.BTCUSDT.1m",
        observed_at=at,
        state="STALE",
        reason="RATE_LIMIT",
        requests=1,
        network_bytes=0,
        blocked_until=at + timedelta(seconds=seconds),
        cooldown_host=host,
    )


def test_host_cooldown_release_allows_exactly_one_probe(store):
    now = datetime.now(UTC)
    store.event(cooldown_event("rest.1", REST_HOST, now - MINUTE, 3 * 86400))
    assert store.cooldown_state(now, REST_HOST) == ("BLOCKED", None)
    assert store.cooldown_state(now, ARCHIVE_HOST) == ("CLEAR", None)
    with pytest.raises(ValueError, match="^NO_ACTIVE_COOLDOWN$"):
        store.release_cooldown(ARCHIVE_HOST, "owner.review", "no archive cooldown exists", now)
    release_id, release = store.release_cooldown(
        REST_HOST, "owner.review", "provider limit confirmed lifted", now
    )
    assert release.released_events == ("rest.1",)
    later = now + MINUTE
    assert store.cooldown_state(later, REST_HOST) == ("PROBE_AVAILABLE", release_id)
    store.start_probe(release_id, "https://data-api.binance.vision/api/v3/time", later)
    with pytest.raises(IntegrityError):
        store.start_probe(release_id, "https://data-api.binance.vision/api/v3/time", later)
    assert store.cooldown_state(later, REST_HOST) == ("BLOCKED", None)
    store.probe_result(release_id, True, "PROBE_PASSED", later + MINUTE)
    assert store.cooldown_state(later + 2 * MINUTE, REST_HOST) == ("CLEAR", None)
    (span,) = store.cooldowns_between(now - HOUR, now + timedelta(days=4))
    assert (span.event_id, span.host, span.end) == ("rest.1", REST_HOST, later + MINUTE)
    # A legacy cooldown without a host still blocks every host.
    legacy = cooldown_event("legacy", ARCHIVE_HOST, later).model_copy(
        update={"cooldown_host": None}
    )
    store.event(legacy)
    assert store.cooldown_state(later + 2 * MINUTE, ARCHIVE_HOST)[0] == "BLOCKED"
    assert store.cooldown_state(later + 2 * MINUTE, REST_HOST)[0] == "BLOCKED"
    # The database binds the host column to the event payload and refuses a release
    # when nothing is cooling down.
    with pytest.raises(DBAPIError, match="data_event_cooldown_host_bound"):
        with store.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO data_event(event_id,feed_key,observed_at,blocked_until,"
                    "cooldown_host,payload) VALUES ('forged','x',now(),now(),:h,:p)"
                ),
                {"h": ARCHIVE_HOST, "p": json.dumps({"cooldown_host": REST_HOST})},
            )
    with pytest.raises(DBAPIError, match="NO_ACTIVE_COOLDOWN"):
        with store.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO data_cooldown_release VALUES "
                    "(:i,:h,:t,'owner','a sufficiently long reason',:u,'{}')"
                ),
                {"i": "c" * 64, "h": ARCHIVE_HOST, "t": now - 2 * HOUR, "u": now},
            )


def one_minute_window(store, day):
    """Twelve genuine minutes for both symbols inside one day's scheduled window."""
    window = datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=18)
    for minute in range(12):
        for symbol in ("BTCUSDT", "ETHUSDT"):
            observed = window + minute * MINUTE + timedelta(seconds=15)
            end = observed.replace(second=0)
            start = end - MINUTE
            values = row(start)
            values[6] = str((end - EPOCH) // timedelta(milliseconds=1) - 1)
            raw = json.dumps([values]).encode()
            begin_ms = (start - EPOCH) // timedelta(milliseconds=1)
            end_ms = (end - EPOCH) // timedelta(milliseconds=1) - 1
            url = (
                f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}"
                f"&interval=1m&startTime={begin_ms}&endTime={end_ms}&limit=1000"
            )
            bars, report = parse_rest(raw, symbol, "1m", start, end, observed, url)
            manifest = store.publish(
                bars,
                report,
                identity("DS-02", observed),
                rights("DS-02", observed),
                f"DS-02.{symbol}.1m.{begin_ms}.{end_ms}",
                url,
                raw,
                observed,
                "synthetic-test",
            )
            store.event(
                IngestionEvent(
                    event_id=f"{day}.{minute}.{symbol}",
                    feed_key=f"DS-02.{symbol}.1m",
                    observed_at=observed,
                    state="FRESH",
                    reason="CANDLES_PASS",
                    requests=2,
                    network_bytes=len(raw),
                    dataset_version=manifest.dataset_version,
                )
            )


def test_bounded_qualification_and_verification_beyond_ten_thousand_rows(store, monkeypatch):
    day = date(2026, 10, 18)
    one_minute_window(store, day)
    # 10,050 unrelated events across the preceding fortnight, outside every window.
    with store.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO data_event(event_id,feed_key,observed_at,payload) "
                "SELECT 'noise.'||n,'DS-02.BTCUSDT.1m',"
                "TIMESTAMPTZ '2026-10-03 00:00:00+00'+n*interval '1 minute',"
                "json_build_object('schema_version','1.0','event_id','noise.'||n,"
                "'feed_key','DS-02.BTCUSDT.1m','observed_at',"
                "to_char((TIMESTAMPTZ '2026-10-03 00:00:00+00'+n*interval '1 minute') "
                "AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'),"
                "'state','STALE','reason','CANDLES_DEGRADED','requests',1,"
                "'network_bytes',0)::text FROM generate_series(1,10050) n"
            )
        )
    assert count(store, "data_event") == 10050 + 24
    # The whole-table loader still fails closed; qualification no longer depends on it.
    with pytest.raises(ValueError, match="REPORT_BUDGET_EXCEEDED"):
        store.events()
    events, manifests, cooldowns, gaps = store.qualification_inputs(day)
    assert len(events) == len(manifests) == 24 and cooldowns == () and gaps == []
    report = qualification(
        events,
        day,
        datetime(2026, 10, 25, tzinfo=UTC),
        manifests,
        receipts(day),
        cooldowns,
        gaps,
    )
    assert [d["status"] for d in report["days"]] == ["PASS"] + ["INCOMPLETE"] * 6
    assert report["days"][0]["verified_events"] == 24
    # Keyset pages of five still verify every manifest exactly once.
    monkeypatch.setattr(data_store, "PAGE_ROWS", 5)
    assert sum(len(page) for page in store.manifest_pages()) == 24
    assert store.reconcile() == {
        "verified_manifests": 24,
        "unpublished_orphans": 0,
        "staging_files": 0,
    }
    orphan = store.root / "partitions" / "binance.spot.BTCUSDT" / ("e" * 64 + ".parquet")
    orphan.write_bytes(b"unpublished")
    assert store.reconcile()["unpublished_orphans"] == 1
    assert (
        len(
            store.events_between(
                datetime(2026, 10, 3, tzinfo=UTC), datetime(2026, 10, 4, tzinfo=UTC)
            )
        )
        == 1439
    )


def test_recovery_drill_covers_every_append_only_data_and_research_table():
    """The data recovery drill compares and trigger-probes every guarded table, 0006 too."""
    with generated_database() as name:
        engine = engine_for(name)
        try:
            with engine.connect() as conn:
                guarded = set(
                    conn.scalars(
                        text(
                            "SELECT DISTINCT c.relname FROM pg_trigger t "
                            "JOIN pg_class c ON c.oid=t.tgrelid "
                            "JOIN pg_proc p ON p.oid=t.tgfoid "
                            "WHERE p.proname='refuse_foundation_mutation' "
                            "AND c.relname ~ '^(data|research)_'"
                        )
                    )
                )
                assert guarded == set(IMMUTABLE)
                for table in TABLES:
                    conn.execute(text(f"SELECT t.* FROM {table} AS t ORDER BY t::text"))
            for table in IMMUTABLE:
                with pytest.raises(DBAPIError), engine.begin() as conn:
                    conn.execute(text(f"DELETE FROM {table}"))
        finally:
            engine.dispose()

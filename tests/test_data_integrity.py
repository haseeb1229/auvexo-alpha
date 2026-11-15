"""Cross-source comparison, reviewed gaps and host cooldowns without a database.

Synthetic fixtures only; none of this is source qualification evidence.
"""

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from pydantic import ValidationError
from test_data_clock_proof import CLOCK_URL, FEED, HEAD, MINUTE, World, collector_for
from test_data_gates import observation_fixtures, qualification, receipts
from test_data_parser import row

from auvexo_alpha.application.data_quality import (
    compare_sources,
    cooldown_spans,
    cooldown_state,
    gap_evidence_refusal,
    market_values,
)
from auvexo_alpha.domain.market_data import (
    ARCHIVE_HOST,
    REST_HOST,
    CooldownRelease,
    CooldownSpan,
    DataQualityFinding,
    GapObservation,
    GapReview,
    IngestionEvent,
)
from auvexo_alpha.infrastructure.data_collection import PROBE_URLS
from auvexo_alpha.infrastructure.public_http import SourceError
from auvexo_alpha.infrastructure.source_registry import identity, rights
from auvexo_alpha.infrastructure.spot_parser import parse_row

HOUR = timedelta(hours=1)
T0 = datetime(2026, 10, 20, 10, tzinfo=UTC)


def hourly(source, start, price="100", received=None):
    received = received or start + 2 * HOUR
    return parse_row(
        row(start, price=price),
        "BTCUSDT",
        "1h",
        "MILLISECOND",
        source,
        "https://fixture.invalid/" + source,
        sha256(source.encode()).hexdigest(),
        received,
    )


def manifest(source, label, start, end, findings=(), created=None):
    """A synthetic stored manifest; only the fields these pure checks read are meaningful."""
    template = observation_fixtures()[2][0]
    digest = sha256(label.encode()).hexdigest()
    coverage = template.coverage.model_copy(
        update=dict(
            interval="1h",
            requested_start=start,
            requested_end=end,
            findings=tuple(findings),
            status="DEGRADED" if findings else "PASS",
        )
    )
    return template.model_copy(
        update=dict(
            dataset_version=digest,
            source_hash=sha256(digest.encode()).hexdigest(),
            source=identity(source),
            rights=rights(source),
            logical_key=f"{source}.BTCUSDT.1h.{label}",
            coverage=coverage,
            created_at=created or end + MINUTE,
        )
    )


def side(source, label, *bars):
    start, end = bars[0].open_at, bars[-1].end_at
    return manifest(source, label, start, end), list(bars)


def test_identical_archive_and_rest_bars_reconcile_and_are_not_rewritten():
    archive = side("DS-01", "a", hourly("DS-01", T0), hourly("DS-01", T0 + HOUR))
    rest = side("DS-02", "r", hourly("DS-02", T0), hourly("DS-02", T0 + HOUR))
    before = [b.canonical_bytes() for _, bars in (archive, rest) for b in bars]
    comparison, conflicts = compare_sources(
        [archive], [rest], "binance.spot.BTCUSDT", "1h", T0, T0 + 2 * HOUR
    )
    assert (comparison.matched, comparison.archive_only, comparison.rest_only) == (2, 0, 0)
    assert conflicts == () and comparison.conflicts == ()
    assert before == [b.canonical_bytes() for _, bars in (archive, rest) for b in bars]


def test_conflict_keeps_both_sources_and_their_own_rights_without_choosing():
    early = T0 + 3 * HOUR
    archive = side("DS-01", "a", hourly("DS-01", T0, received=early))
    rest = side("DS-02", "r", hourly("DS-02", T0, price="101", received=T0 + 2 * HOUR))
    comparison, (conflict,) = compare_sources(
        [archive], [rest], "binance.spot.BTCUSDT", "1h", T0, T0 + HOUR
    )
    assert comparison.matched == 0 and comparison.conflicts == (conflict.content_hash(),)
    assert (conflict.archive_version, conflict.rest_version) == (
        archive[0].dataset_version,
        rest[0].dataset_version,
    )
    assert conflict.archive_rights_version == rights("DS-01").version
    assert conflict.rest_rights_version == rights("DS-02").version
    # Hand-checked values: only the open differs (100 against 101), nothing is averaged.
    assert conflict.archive_values[2:] == ("100", "110", "90", "105", "3", "300", "4")
    assert conflict.rest_values[2:] == ("101", "110", "90", "105", "3", "300", "4")
    # Knowable only once the later of the two bars was available, never earlier.
    assert conflict.known_at == early == archive[1][0].availability.available_at
    assert market_values(archive[1][0]) == conflict.archive_values


def test_revised_rest_versions_are_each_compared_and_absences_counted():
    archive = side("DS-01", "a", hourly("DS-01", T0), hourly("DS-01", T0 + HOUR))
    first = side("DS-02", "r1", hourly("DS-02", T0))
    revised = side("DS-02", "r2", hourly("DS-02", T0, price="99"))
    late = side("DS-02", "r3", hourly("DS-02", T0 + 2 * HOUR))
    comparison, conflicts = compare_sources(
        [archive], [first, revised, late], "binance.spot.BTCUSDT", "1h", T0, T0 + 3 * HOUR
    )
    # T0: one match and one conflict; T0+1h archive only; T0+2h REST only.
    assert (comparison.matched, len(conflicts)) == (1, 1)
    assert (comparison.archive_only, comparison.rest_only) == (1, 1)
    assert conflicts[0].rest_version == revised[0].dataset_version
    reordered, again = compare_sources(
        [archive], [late, revised, first], "binance.spot.BTCUSDT", "1h", T0, T0 + 3 * HOUR
    )
    assert reordered.content_hash() == comparison.content_hash() and again == conflicts


def test_comparison_refuses_mixed_sources_and_misaligned_ranges():
    archive = side("DS-01", "a", hourly("DS-01", T0))
    rest = side("DS-02", "r", hourly("DS-02", T0))
    with pytest.raises(ValueError, match="^COMPARISON_SOURCE_MISMATCH$"):
        compare_sources([rest], [rest], "binance.spot.BTCUSDT", "1h", T0, T0 + HOUR)
    with pytest.raises(ValueError, match="^COMPARISON_SOURCE_MISMATCH$"):
        compare_sources([archive], [rest], "binance.spot.ETHUSDT", "1h", T0, T0 + HOUR)
    with pytest.raises(ValueError, match="^COMPARISON_RANGE_INVALID$"):
        compare_sources([archive], [rest], "binance.spot.BTCUSDT", "1h", T0, T0 + MINUTE)


def gap_finding(first, last):
    return DataQualityFinding(code="GAP", count=1, first_at=first, last_at=last, detail="absent")


def absent_response(label, received):
    """A stored REST response for [T0, T0+3h) that omits the T0+1h bar."""
    stored = manifest(
        "DS-02", label, T0, T0 + 3 * HOUR, [gap_finding(T0 + HOUR, T0 + HOUR)], received
    )
    return stored, [hourly("DS-02", T0), hourly("DS-02", T0 + 2 * HOUR)]


def review(*responses, start=T0 + HOUR, end=T0 + 2 * HOUR):
    return GapReview(
        feed_key="DS-02.BTCUSDT.1h",
        instrument_id="binance.spot.BTCUSDT",
        interval="1h",
        gap_start=start,
        gap_end=end,
        evidence=tuple(
            GapObservation(
                dataset_version=m.dataset_version,
                source_hash=m.source_hash,
                received_at=m.created_at,
            )
            for m, _ in responses
        ),
        reviewer="owner.review",
        reviewed_at=T0 + 6 * HOUR,
    )


def test_missing_bar_repeated_in_distinct_responses_is_accepted():
    responses = [absent_response("p1", T0 + 3 * HOUR), absent_response("p2", T0 + 4 * HOUR)]
    assert gap_evidence_refusal(review(*responses), responses, responses, T0) is None


def test_same_response_twice_or_once_is_not_repeated_evidence():
    first = absent_response("p1", T0 + 3 * HOUR)
    with pytest.raises(ValidationError, match="GAP_EVIDENCE_NOT_REPEATED"):
        review(first, first)
    with pytest.raises(ValidationError):
        review(first)
    # Different stored versions received at the same instant are still one observation.
    twin = absent_response("p2", T0 + 3 * HOUR)
    with pytest.raises(ValidationError, match="GAP_EVIDENCE_NOT_REPEATED"):
        review(first, twin)


def test_any_stored_response_holding_the_bar_contradicts_the_gap():
    responses = [absent_response("p1", T0 + 3 * HOUR), absent_response("p2", T0 + 4 * HOUR)]
    reviewed = review(*responses)
    present = manifest("DS-02", "p3", T0, T0 + 3 * HOUR, (), T0 + 5 * HOUR)
    holding = (present, [hourly("DS-02", T0 + HOUR)])
    assert gap_evidence_refusal(reviewed, responses, [*responses, holding], T0) == (
        "GAP_EVIDENCE_CONFLICT"
    )
    # Evidence that itself carries the bar can never prove its absence.
    conflicted = (responses[1][0], [*responses[1][1], hourly("DS-02", T0 + HOUR)])
    assert gap_evidence_refusal(reviewed, [responses[0], conflicted], [], T0) == (
        "GAP_EVIDENCE_CONFLICT"
    )


@pytest.mark.parametrize(
    "fault,code",
    [
        ("no_checkpoint", "GAP_FEED_HAS_NO_CHECKPOINT"),
        ("past_checkpoint", "GAP_BEFORE_CHECKPOINT"),
        ("not_stored", "GAP_EVIDENCE_NOT_STORED"),
        ("archive", "GAP_EVIDENCE_SOURCE_MISMATCH"),
        ("unrecorded", "GAP_NOT_RECORDED_BY_EVIDENCE"),
        ("narrow_request", "GAP_EVIDENCE_DOES_NOT_REQUEST_RANGE"),
    ],
)
def test_gap_review_refusals(fault, code):
    responses = [absent_response("p1", T0 + 3 * HOUR), absent_response("p2", T0 + 4 * HOUR)]
    checkpoint = T0
    stored = list(responses)
    if fault == "no_checkpoint":
        checkpoint = None
    elif fault == "past_checkpoint":
        checkpoint = T0 + 2 * HOUR
    elif fault == "not_stored":
        stored = stored[:1]
    elif fault == "archive":
        stored[0] = (stored[0][0].model_copy(update={"source": identity("DS-01")}), stored[0][1])
    elif fault == "unrecorded":
        coverage = stored[0][0].coverage.model_copy(update={"findings": ()})
        stored[0] = (stored[0][0].model_copy(update={"coverage": coverage}), stored[0][1])
    else:
        coverage = stored[0][0].coverage.model_copy(update={"requested_end": T0 + HOUR})
        stored[0] = (stored[0][0].model_copy(update={"coverage": coverage}), stored[0][1])
    assert gap_evidence_refusal(review(*responses), stored, [], checkpoint) == code


@pytest.mark.parametrize(
    "start,end",
    [
        (T0 + HOUR + MINUTE, T0 + 2 * HOUR),  # not aligned to the bar interval
        (T0 + HOUR, T0 + HOUR),  # empty
        (T0, T0 + 1441 * HOUR),  # longer than a reviewed gap may be
    ],
)
def test_gap_range_must_be_aligned_nonempty_and_bounded(start, end):
    responses = [absent_response("p1", T0 + 3 * HOUR), absent_response("p2", T0 + 4 * HOUR)]
    with pytest.raises(ValidationError, match="GAP_RANGE_INVALID"):
        review(*responses, start=start, end=end)


def test_day_with_a_reviewed_gap_or_any_cooldown_never_qualifies():
    start, events, manifests = observation_fixtures()
    scheduled = receipts(start.date())
    passed = qualification(events, start.date(), start + timedelta(days=7), manifests, scheduled)
    assert passed["status"] == "PASS"
    responses = [absent_response("p1", T0 + 3 * HOUR), absent_response("p2", T0 + 4 * HOUR)]
    # T0 is 2026-10-20 10:00 UTC: the gap lies hours before that day's window and still fails it.
    gapped = qualification(
        events,
        start.date(),
        start + timedelta(days=7),
        manifests,
        scheduled,
        gaps=[review(*responses)],
    )
    assert [d["status"] for d in gapped["days"]] == ["PASS"] * 2 + ["INCOMPLETE"] + ["PASS"] * 4
    assert gapped["days"][2]["reviewed_gaps"] == ["DS-02.BTCUSDT.1h:2026-10-20T11:00:00+00:00"]
    # A cooldown on the archive host at 03:00 on the 22nd ends in time but the day stays failed.
    cooldown = CooldownSpan(
        event_id="c1",
        host=ARCHIVE_HOST,
        reason="RATE_LIMIT",
        start=datetime(2026, 10, 22, 3, tzinfo=UTC),
        end=datetime(2026, 10, 22, 3, 1, tzinfo=UTC),
    )
    cooled = qualification(
        events,
        start.date(),
        start + timedelta(days=7),
        manifests,
        scheduled,
        cooldowns=[cooldown],
    )
    assert [d["status"] for d in cooled["days"]] == ["PASS"] * 4 + ["INCOMPLETE"] + ["PASS"] * 2
    assert cooled["days"][4]["provider_cooldowns"] == ["c1"] and cooled["status"] == "OPEN"
    # A cooldown spanning midnight fails both calendar days it touches; one ending exactly
    # at midnight touches only the first.
    spanning = cooldown.model_copy(
        update={
            "start": datetime(2026, 10, 18, 23, tzinfo=UTC),
            "end": datetime(2026, 10, 19, 0, 0, 1, tzinfo=UTC),
        }
    )
    edge = cooldown.model_copy(update={"end": datetime(2026, 10, 23, tzinfo=UTC)})
    days = qualification(
        events,
        start.date(),
        start + timedelta(days=7),
        manifests,
        scheduled,
        cooldowns=[spanning, edge],
    )["days"]
    assert [d["status"] for d in days] == ["INCOMPLETE"] * 2 + ["PASS"] * 2 + ["INCOMPLETE"] + [
        "PASS"
    ] * 2


def blocked(event_id, host, at, seconds=3600):
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


def release(host, at, *events):
    return CooldownRelease(
        host=host,
        released_at=at,
        reviewer="owner.review",
        reason="provider limit confirmed lifted",
        released_until=max(e.blocked_until for e in events),
        released_events=tuple(e.event_id for e in events),
    )


def test_cooldowns_are_scoped_per_host_and_legacy_ones_stay_global():
    rest = blocked("r", REST_HOST, T0)
    legacy = blocked("l", None, T0).model_copy(update={"cooldown_host": None})
    now = T0 + MINUTE
    assert cooldown_state(now, REST_HOST, [rest], None, False, False) == "BLOCKED"
    assert cooldown_state(now, ARCHIVE_HOST, [rest], None, False, False) == "CLEAR"
    assert cooldown_state(now, ARCHIVE_HOST, [legacy], None, False, False) == "BLOCKED"
    # Expiry is exclusive: at blocked_until the host is clear again.
    assert cooldown_state(T0 + HOUR, REST_HOST, [rest], None, False, False) == "CLEAR"
    with pytest.raises(ValidationError, match="COOLDOWN_HOST_WITHOUT_COOLDOWN"):
        IngestionEvent.model_validate(rest.model_dump() | {"blocked_until": None})


def test_owner_release_grants_exactly_one_probe_and_only_a_pass_clears():
    rest = blocked("r", REST_HOST, T0)
    now = T0 + 2 * MINUTE
    owner = release(REST_HOST, T0 + MINUTE, rest)
    assert cooldown_state(now, REST_HOST, [rest], owner, False, False) == "PROBE_AVAILABLE"
    assert cooldown_state(now, REST_HOST, [rest], owner, True, False) == "BLOCKED"
    assert cooldown_state(now, REST_HOST, [rest], owner, True, True) == "CLEAR"
    # A release for the other host, or made before a newer cooldown, frees nothing.
    other = release(ARCHIVE_HOST, T0 + MINUTE, rest)
    assert cooldown_state(now, REST_HOST, [rest], other, False, False) == "BLOCKED"
    newer = blocked("r2", REST_HOST, T0 + 90 * timedelta(seconds=1))
    assert cooldown_state(now, REST_HOST, [rest, newer], owner, True, True) == "BLOCKED"


def test_cooldown_span_ends_at_a_passed_probe_or_at_expiry():
    rest = blocked("r", REST_HOST, T0, seconds=3 * 86400)
    archive = blocked("a", ARCHIVE_HOST, T0)
    owner = release(REST_HOST, T0 + MINUTE, rest)
    spans = cooldown_spans([rest, archive], [(owner, T0 + 2 * MINUTE)])
    assert [(s.event_id, s.start, s.end) for s in spans] == [
        ("a", T0, T0 + HOUR),
        ("r", T0, T0 + 2 * MINUTE),
    ]


def test_legacy_cooldown_span_ends_per_host_like_cooldown_state():
    legacy = blocked("l", None, T0, seconds=3 * 86400).model_copy(update={"cooldown_host": None})
    owner = release(ARCHIVE_HOST, T0 + HOUR, legacy)
    spans = cooldown_spans([legacy], [(owner, T0 + 2 * HOUR)])
    # The archive probe ends only the archive span; REST stays blocked to the true expiry.
    assert sorted((s.host, s.end) for s in spans) == sorted(
        [(ARCHIVE_HOST, T0 + 2 * HOUR), (REST_HOST, T0 + timedelta(days=3))]
    )
    now = T0 + 3 * HOUR
    assert cooldown_state(now, ARCHIVE_HOST, [legacy], owner, True, True) == "CLEAR"
    assert cooldown_state(now, REST_HOST, [legacy], owner, True, True) == "BLOCKED"


def test_released_host_gets_one_probe_then_collects(monkeypatch):
    world = World()
    collector, store = collector_for(monkeypatch, world)
    store.behind(FEED, HEAD - 2 * MINUTE)
    store.cooldowns[REST_HOST] = ("PROBE_AVAILABLE", "release.1")
    manifest = collector.poll("BTCUSDT")
    assert manifest.coverage.status == "PASS"
    assert world.urls[0] == PROBE_URLS[REST_HOST] == CLOCK_URL
    assert store.probes == [("release.1", CLOCK_URL), ("release.1", "PASSED", "PROBE_PASSED")]
    assert [e.reason for e in store.events][:1] == ["COOLDOWN_PROBE_PASSED"]


def test_failed_probe_records_a_new_host_cooldown_and_sends_nothing_else(monkeypatch):
    world = World()
    world.status = 429
    collector, store = collector_for(monkeypatch, world)
    store.cooldowns[REST_HOST] = ("PROBE_AVAILABLE", "release.1")
    with pytest.raises(SourceError, match="^COOLDOWN_PROBE_FAILED$"):
        collector.poll("BTCUSDT")
    assert world.urls == [CLOCK_URL] and collector.http.requests == 1
    (event,) = store.events
    assert (event.reason, event.cooldown_host) == ("RATE_LIMIT", REST_HOST)
    assert store.probes[-1] == ("release.1", "FAILED", "RATE_LIMIT")
    # The single probe is spent: the next attempt is refused before any request.
    with pytest.raises(SourceError, match="PERSISTED_PROVIDER_COOLDOWN"):
        collector.poll("BTCUSDT")
    assert world.urls == [CLOCK_URL]


def test_archive_cooldown_does_not_stop_the_rest_feed(monkeypatch):
    world = World()
    collector, store = collector_for(monkeypatch, world)
    store.behind(FEED, HEAD - 2 * MINUTE)
    store.cooldowns[ARCHIVE_HOST] = ("BLOCKED", None)
    assert collector.poll("BTCUSDT").coverage.status == "PASS"
    with pytest.raises(SourceError, match="PERSISTED_PROVIDER_COOLDOWN"):
        collector.history("BTCUSDT", "1h", "2024-12-31")


def test_reviewed_gap_lets_the_wedged_feed_move_past_without_filling(monkeypatch):
    world = World()
    collector, store = collector_for(monkeypatch, world)
    start = HEAD - 10 * MINUTE
    missing = start + 4 * MINUTE
    store.behind(FEED, start)
    world.missing = {missing}
    # Unreviewed, the provider gap wedges the feed: every poll repeats the same range.
    for _ in range(2):
        assert collector.poll("BTCUSDT").coverage.status == "DEGRADED"
        assert store.checkpoints[FEED].next_open == start
        world.provider_now += MINUTE
    evidence = [m for _, m in store.published]
    store.reviewed_gaps.append(
        GapReview(
            feed_key=FEED,
            instrument_id="binance.spot.BTCUSDT",
            interval="1m",
            gap_start=missing,
            gap_end=missing + MINUTE,
            evidence=tuple(
                GapObservation(
                    dataset_version=m.dataset_version,
                    source_hash=m.source_hash,
                    received_at=m.created_at,
                )
                for m in evidence
            ),
            reviewer="owner.review",
            reviewed_at=world.local_now() + MINUTE,
        )
    )
    before_gap = collector.poll("BTCUSDT")
    assert (before_gap.coverage.requested_start, before_gap.coverage.requested_end) == (
        start,
        missing,
    )
    assert before_gap.coverage.status == "PASS" and store.checkpoints[FEED].next_open == missing
    after_gap = collector.poll("BTCUSDT")
    assert after_gap.coverage.requested_start == missing + MINUTE
    assert after_gap.coverage.status == "PASS"
    assert store.checkpoints[FEED].next_open == after_gap.coverage.requested_end
    published = [bar.open_at for bars, _ in store.published for bar in bars]
    assert missing not in published


def test_operator_probe_targets_are_fixed_allowlisted_objects():
    from auvexo_alpha.infrastructure.public_http import allowed_url

    assert set(PROBE_URLS) == {ARCHIVE_HOST, REST_HOST}
    assert all(allowed_url(url) for url in PROBE_URLS.values())

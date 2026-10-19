"""Synthetic timing-independent ADR-022 qualification; never rerun the benchmark."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path

import pytest

from auvexo_alpha.domain.paper_performance import (
    PerformanceStatus,
    evaluate_paper_performance,
)

PHASES = ("research_concurrent", "research_throttled")
METRICS = ("kernel", "reservation_transaction", "indexed_query", "baseline", "5x_burst")
FIELDS = ("samples", "p50_ms", "p95_ms", "p99_ms", "max_ms")


def summary(samples, p50, p95, p99, maximum):
    return dict(samples=samples, p50_ms=p50, p95_ms=p95, p99_ms=p99, max_ms=maximum)


@pytest.fixture
def receipt():
    def wave(offered):
        return dict(
            offered=offered,
            admitted=32,
            backpressured=offered - 32,
            queue_bound=32,
            peak_depth=32,
            drained=True,
            concurrent_workers=2,
            actual_reservation_transactions=summary(32, 5.0, 10.0, 15.0, 20.0),
            wave_elapsed_seconds=1.0,
        )

    def phase():
        return dict(
            kernel=summary(1000, 1.0, 2.0, 3.0, 4.0),
            reservation_transaction=summary(120, 10.0, 20.0, 30.0, 40.0),
            indexed_query=summary(360, 2.0, 4.0, 6.0, 8.0),
            backpressure={"baseline": wave(32), "5x_burst": wave(160)},
            # The old primary-only MAX boolean is deliberately not authority.
            targets_met={"transaction_max": False},
        )

    return dict(
        evidence_kind="SYNTHETIC_ENGINEERING_ONLY",
        benchmark_version="paper.synthetic.three_instrument.v1",
        load_policy=dict(queue_depth=32, burst_multiple=5, database_workers=2),
        instruments=["paper.spot.BTCUSD", "paper.spot.ETHUSD", "paper.spot.SYNTHUSD"],
        persistent_task=False,
        observation_days=0,
        phases={phase_name: phase() for phase_name in PHASES},
        resources={"evidence": "SYNTHETIC_TEST_ONLY"},
    )


def metric(receipt, phase, name):
    data = receipt["phases"][phase]
    if name in ("baseline", "5x_burst"):
        return data["backpressure"][name]["actual_reservation_transactions"]
    return data[name]


def result_phase(result, name):
    return next(phase for phase in result.phases if phase.name == name)


def result_metric(result, phase, name):
    return next(value for value in result_phase(result, phase).metrics if value.name == name)


def change_percentile(data, field, value):
    data[field] = value
    if field == "p95_ms":
        data["p99_ms"] = max(data["p99_ms"], value)
    data["max_ms"] = max(data["max_ms"], value)


def test_p4_qualified_synthetic_receipt_reports_each_set_and_does_not_mutate_input(receipt):
    original = deepcopy(receipt)
    result = evaluate_paper_performance(receipt)
    assert result.status == PerformanceStatus.PASS
    assert receipt == original
    assert tuple(phase.name for phase in result.phases) == PHASES
    for phase in PHASES:
        assert result_phase(result, phase).status == PerformanceStatus.PASS
        assert tuple(value.name for value in result_phase(result, phase).metrics) == METRICS
        for name in METRICS:
            actual, expected = result_metric(result, phase, name), metric(receipt, phase, name)
            assert {field: getattr(actual, field) for field in FIELDS} == expected
    with pytest.raises(FrozenInstanceError):
        result.status = PerformanceStatus.FAIL
    with pytest.raises(FrozenInstanceError):
        result.phases[0].status = PerformanceStatus.FAIL
    with pytest.raises(FrozenInstanceError):
        result.phases[0].metrics[0].max_ms = 0


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize(
    ("name", "field", "limit"),
    (
        ("kernel", "p95_ms", 10.0),
        ("kernel", "p99_ms", 25.0),
        ("indexed_query", "p95_ms", 50.0),
        ("indexed_query", "p99_ms", 200.0),
    ),
)
@pytest.mark.parametrize("excess", (0.0, 0.0001))
def test_p4_kernel_and_query_percentiles_are_hard_in_both_phases(
    receipt, phase, name, field, limit, excess
):
    change_percentile(metric(receipt, phase, name), field, limit + excess)
    result = evaluate_paper_performance(receipt)
    expected = PerformanceStatus.PASS if excess == 0 else PerformanceStatus.FAIL
    assert result.status == expected
    assert result_phase(result, phase).status == expected
    if excess:
        assert result_phase(result, phase).reasons


@pytest.mark.parametrize("name", ("reservation_transaction", "baseline", "5x_burst"))
@pytest.mark.parametrize(("field", "limit"), (("p95_ms", 100.0), ("p99_ms", 250.0)))
@pytest.mark.parametrize("excess", (0.0, 0.0001))
def test_p4_each_qualified_throttled_transaction_set_enforces_exact_budgets(
    receipt, name, field, limit, excess
):
    change_percentile(metric(receipt, "research_throttled", name), field, limit + excess)
    result = evaluate_paper_performance(receipt)
    expected = PerformanceStatus.PASS if excess == 0 else PerformanceStatus.FAIL
    assert result.status == expected
    assert result_phase(result, "research_throttled").status == expected


@pytest.mark.parametrize("name", ("reservation_transaction", "baseline", "5x_burst"))
@pytest.mark.parametrize(("field", "limit"), (("p95_ms", 100.0), ("p99_ms", 250.0)))
def test_p4_concurrent_stress_is_explicit_throttle_trigger_then_qualified_throttled_pass(
    receipt, name, field, limit
):
    change_percentile(metric(receipt, "research_concurrent", name), field, limit + 1)
    result = evaluate_paper_performance(receipt)
    assert result.status == PerformanceStatus.PASS
    concurrent = result_phase(result, "research_concurrent")
    assert concurrent.status == PerformanceStatus.THROTTLE_REQUIRED
    assert concurrent.reasons
    assert result_phase(result, "research_throttled").status == PerformanceStatus.PASS
    assert getattr(result_metric(result, "research_concurrent", name), field) == limit + 1


@pytest.mark.parametrize("failure", ("missing", "p95", "p99", "queue", "kernel", "query"))
def test_p4_concurrent_trigger_cannot_qualify_without_valid_throttled_recovery(receipt, failure):
    change_percentile(metric(receipt, "research_concurrent", "baseline"), "p95_ms", 130.0)
    if failure == "missing":
        del receipt["phases"]["research_throttled"]
    elif failure in ("p95", "p99"):
        change_percentile(
            metric(receipt, "research_throttled", "baseline"),
            failure + "_ms",
            101.0 if failure == "p95" else 251.0,
        )
    elif failure == "queue":
        receipt["phases"]["research_throttled"]["backpressure"]["5x_burst"]["drained"] = False
    else:
        change_percentile(
            metric(
                receipt, "research_throttled", "indexed_query" if failure == "query" else failure
            ),
            "p95_ms",
            11.0 if failure == "kernel" else 51.0,
        )
    result = evaluate_paper_performance(receipt)
    assert result.status == PerformanceStatus.FAIL
    assert result_phase(result, "research_concurrent").status == PerformanceStatus.THROTTLE_REQUIRED
    assert result_phase(result, "research_throttled").status == PerformanceStatus.FAIL


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("name", METRICS)
def test_p4_all_maxima_above_100_remain_reported_without_outlier_filtering(receipt, phase, name):
    metric(receipt, phase, name)["max_ms"] = 9000.25
    original = deepcopy(receipt)
    result = evaluate_paper_performance(receipt)
    assert result.status == PerformanceStatus.PASS
    assert result_metric(result, phase, name).max_ms == 9000.25
    assert result_metric(result, phase, name).samples == metric(receipt, phase, name)["samples"]
    assert receipt == original


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("wave", ("baseline", "5x_burst"))
@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("offered", 159),
        ("admitted", 31),
        ("admitted", 33),
        ("backpressured", 1),
        ("queue_bound", 33),
        ("peak_depth", 33),
        ("peak_depth", 31),
        ("concurrent_workers", 1),
        ("concurrent_workers", 3),
        ("drained", False),
        ("drained", 1),
        ("admitted", True),
    ),
)
def test_p4_queue_workload_accounting_and_drain_failures_never_qualify(
    receipt, phase, wave, field, value
):
    receipt["phases"][phase]["backpressure"][wave][field] = value
    result = evaluate_paper_performance(receipt)
    assert result.status == PerformanceStatus.FAIL
    assert result_phase(result, phase).status == PerformanceStatus.FAIL


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("wave", ("baseline", "5x_burst"))
@pytest.mark.parametrize(
    "field",
    (
        "offered",
        "admitted",
        "backpressured",
        "queue_bound",
        "peak_depth",
        "concurrent_workers",
        "drained",
    ),
)
def test_p4_missing_queue_evidence_fails(receipt, phase, wave, field):
    del receipt["phases"][phase]["backpressure"][wave][field]
    assert evaluate_paper_performance(receipt).status == PerformanceStatus.FAIL


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("name", METRICS)
@pytest.mark.parametrize("field", FIELDS)
def test_p4_every_missing_metric_field_or_sample_count_fails(receipt, phase, name, field):
    del metric(receipt, phase, name)[field]
    result = evaluate_paper_performance(receipt)
    assert result.status == PerformanceStatus.FAIL
    assert result_phase(result, phase).reasons


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("name", METRICS)
@pytest.mark.parametrize("value", (0, 1, 31, 119, 999, True, 32.0, "32", None))
def test_p4_fixed_sample_counts_are_required_and_not_coerced(receipt, phase, name, value):
    metric(receipt, phase, name)["samples"] = value
    assert evaluate_paper_performance(receipt).status == PerformanceStatus.FAIL


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("name", METRICS)
@pytest.mark.parametrize("field", FIELDS[1:])
@pytest.mark.parametrize("value", (float("nan"), float("inf"), -1.0, True, "2", None))
def test_p4_malformed_or_nonfinite_metric_values_fail_without_conversion(
    receipt, phase, name, field, value
):
    metric(receipt, phase, name)[field] = value
    assert evaluate_paper_performance(receipt).status == PerformanceStatus.FAIL


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("name", METRICS)
@pytest.mark.parametrize("order", ("p50_p95", "p95_p99", "p99_max"))
def test_p4_percentiles_must_preserve_order(receipt, phase, name, order):
    data = metric(receipt, phase, name)
    first, second = order.split("_")
    data[first + "_ms"] = data[second + "_ms"] + 1
    assert evaluate_paper_performance(receipt).status == PerformanceStatus.FAIL


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("name", METRICS)
@pytest.mark.parametrize("replacement", (None, [], "missing"))
def test_p4_missing_or_malformed_metric_object_fails(receipt, phase, name, replacement):
    if name in ("baseline", "5x_burst"):
        receipt["phases"][phase]["backpressure"][name]["actual_reservation_transactions"] = (
            replacement
        )
    else:
        receipt["phases"][phase][name] = replacement
    assert evaluate_paper_performance(receipt).status == PerformanceStatus.FAIL


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("benchmark_version", "unknown"),
        ("persistent_task", True),
        ("persistent_task", 0),
        ("observation_days", 1),
        ("observation_days", False),
        ("instruments", ["paper.spot.BTCUSD"]),
        ("instruments", ["paper.spot.BTCUSD"] * 3),
        ("load_policy", {"queue_depth": 31, "database_workers": 2, "burst_multiple": 5}),
        ("load_policy", {"queue_depth": 32, "database_workers": 3, "burst_multiple": 5}),
        ("load_policy", {"queue_depth": 32, "database_workers": 2, "burst_multiple": 4}),
        ("phases", {}),
        ("phases", []),
    ),
)
def test_p4_wrong_or_missing_fixed_workload_cannot_qualify(receipt, field, value):
    receipt[field] = value
    assert evaluate_paper_performance(receipt).status == PerformanceStatus.FAIL


@pytest.mark.parametrize(
    "field",
    (
        "evidence_kind",
        "benchmark_version",
        "load_policy",
        "instruments",
        "persistent_task",
        "observation_days",
        "phases",
    ),
)
def test_p4_absent_workload_envelope_evidence_fails(receipt, field):
    del receipt[field]
    assert evaluate_paper_performance(receipt).status == PerformanceStatus.FAIL


def test_p4_integer_metric_values_are_retained_exactly_even_when_phase_fails(receipt):
    data = metric(receipt, "research_throttled", "baseline")
    data.update(p50_ms=10, p95_ms=101, p99_ms=251, max_ms=9001)
    original = deepcopy(receipt)
    first = evaluate_paper_performance(receipt)
    second = evaluate_paper_performance(receipt)
    assert first == second
    assert first.status == PerformanceStatus.FAIL
    retained = result_metric(first, "research_throttled", "baseline")
    assert retained.max_ms == 9001 and type(retained.max_ms) is int
    assert retained.p95_ms == 101 and type(retained.p95_ms) is int
    assert receipt == original


def test_p4_valid_other_metrics_survive_a_malformed_metric_for_honest_reporting(receipt):
    metric(receipt, "research_concurrent", "kernel")["samples"] = 1
    metric(receipt, "research_throttled", "5x_burst")["max_ms"] = 4000.5
    result = evaluate_paper_performance(receipt)
    assert result.status == PerformanceStatus.FAIL
    assert result_metric(result, "research_throttled", "5x_burst").max_ms == 4000.5
    assert result_metric(result, "research_concurrent", "indexed_query").samples == 360


def test_p4_evaluation_does_not_modify_frozen_benchmark_script():
    script = Path(__file__).resolve().parents[1] / "tools" / "benchmark_paper.py"
    assert sha256(script.read_bytes()).hexdigest() == (
        "7c1da5f753dd899a430e3a713f06d79d049eae491b9d9715cb9e761f663bd4fd"
    )

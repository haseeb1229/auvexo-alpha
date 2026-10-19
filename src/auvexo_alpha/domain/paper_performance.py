"""Pure offline interpretation of frozen synthetic PAPER benchmark v1 receipts."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


class PerformanceStatus(StrEnum):
    PASS = "PASS"
    THROTTLE_REQUIRED = "THROTTLE_REQUIRED"
    FAIL = "FAIL"


@dataclass(frozen=True)
class MetricSummary:
    name: str
    samples: int
    p50_ms: int | float
    p95_ms: int | float
    p99_ms: int | float
    max_ms: int | float


@dataclass(frozen=True)
class PhaseEvaluation:
    name: str
    status: PerformanceStatus
    reasons: tuple[str, ...]
    metrics: tuple[MetricSummary, ...]


@dataclass(frozen=True)
class PaperPerformanceEvaluation:
    status: PerformanceStatus
    phases: tuple[PhaseEvaluation, ...]
    reasons: tuple[str, ...]


_PHASES = ("research_concurrent", "research_throttled")
_INSTRUMENTS = ("paper.spot.BTCUSD", "paper.spot.ETHUSD", "paper.spot.SYNTHUSD")


def _mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        return None
    return value


def _integer(value: object, expected: int) -> bool:
    return type(value) is int and value == expected


def _number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except (ValueError, OverflowError):
        return None
    return value if isfinite(result) and result >= 0 else None


def _metric(
    name: str, value: object, expected_samples: int
) -> tuple[MetricSummary | None, tuple[str, ...]]:
    data = _mapping(value)
    if data is None:
        return None, (name + ":METRICS_INVALID",)
    numbers = tuple(_number(data.get(key)) for key in ("p50_ms", "p95_ms", "p99_ms", "max_ms"))
    if any(number is None for number in numbers):
        return None, (name + ":METRICS_INVALID",)
    p50, p95, p99, maximum = numbers
    assert p50 is not None and p95 is not None and p99 is not None and maximum is not None
    if not p50 <= p95 <= p99 <= maximum:
        return None, (name + ":PERCENTILE_ORDER_INVALID",)
    samples = data.get("samples")
    if type(samples) is not int or samples <= 0:
        return None, (name + ":SAMPLE_COUNT_INVALID",)
    result = MetricSummary(name, samples, p50, p95, p99, maximum)
    reasons = () if samples == expected_samples else (name + ":SAMPLE_COUNT_INVALID",)
    return result, reasons


def _phase(name: str, value: object) -> PhaseEvaluation:
    data = _mapping(value)
    if data is None:
        return PhaseEvaluation(name, PerformanceStatus.FAIL, ("PHASE_MISSING_OR_INVALID",), ())
    metrics: list[MetricSummary] = []
    failures: list[str] = []
    throttle: list[str] = []
    for metric_name, samples, p95_limit, p99_limit in (
        ("kernel", 1000, 10, 25),
        ("reservation_transaction", 120, 100, 250),
        ("indexed_query", 360, 50, 200),
    ):
        metric, reasons = _metric(metric_name, data.get(metric_name), samples)
        failures.extend(reasons)
        if metric is not None:
            metrics.append(metric)
            breaches = []
            if metric.p95_ms > p95_limit:
                breaches.append(metric_name + ":P95_BREACH")
            if metric.p99_ms > p99_limit:
                breaches.append(metric_name + ":P99_BREACH")
            if metric_name == "reservation_transaction" and name == "research_concurrent":
                throttle.extend(breaches)
            else:
                failures.extend(breaches)
    admission = _mapping(data.get("backpressure"))
    if admission is None or set(admission) != {"baseline", "5x_burst"}:
        failures.append("QUEUE_SET_INVALID")
    for label, offered, backpressured in (("baseline", 32, 0), ("5x_burst", 160, 128)):
        wave = _mapping(admission.get(label)) if admission is not None else None
        if wave is None:
            failures.append(label + ":QUEUE_MISSING_OR_INVALID")
            continue
        expected = {
            "offered": offered,
            "admitted": 32,
            "backpressured": backpressured,
            "queue_bound": 32,
            "peak_depth": 32,
            "concurrent_workers": 2,
        }
        if (
            any(not _integer(wave.get(key), number) for key, number in expected.items())
            or wave.get("drained") is not True
        ):
            failures.append(label + ":QUEUE_ACCOUNTING_INVALID")
        metric, reasons = _metric(label, wave.get("actual_reservation_transactions"), 32)
        failures.extend(reasons)
        if metric is not None:
            metrics.append(metric)
            breaches = []
            if metric.p95_ms > 100:
                breaches.append(label + ":P95_BREACH")
            if metric.p99_ms > 250:
                breaches.append(label + ":P99_BREACH")
            if name == "research_concurrent":
                throttle.extend(breaches)
            else:
                failures.extend(breaches)
    status = (
        PerformanceStatus.FAIL
        if failures
        else PerformanceStatus.THROTTLE_REQUIRED
        if throttle
        else PerformanceStatus.PASS
    )
    return PhaseEvaluation(name, status, tuple(failures + throttle), tuple(metrics))


def evaluate_paper_performance(report: Mapping[str, object]) -> PaperPerformanceEvaluation:
    """Evaluate all v1 sets without mutating, filtering or rerunning their evidence.

    Concurrent transaction breaches require research throttling. Qualification requires
    both phases' kernel/query/queue invariants and every throttled transaction budget.
    MAX is retained as evidence and is not substituted for the qualified percentiles.
    """
    data = _mapping(report)
    reasons: list[str] = []
    if data is None:
        data = {}
        reasons.append("REPORT_INVALID")
    instruments = data.get("instruments")
    if (
        data.get("benchmark_version") != "paper.synthetic.three_instrument.v1"
        or data.get("evidence_kind") != "SYNTHETIC_ENGINEERING_ONLY"
        or data.get("persistent_task") is not False
        or not _integer(data.get("observation_days"), 0)
        or not isinstance(instruments, (tuple, list))
        or tuple(instruments) != _INSTRUMENTS
    ):
        reasons.append("BENCHMARK_SCOPE_INVALID")
    policy = _mapping(data.get("load_policy"))
    if (
        policy is None
        or set(policy) != {"queue_depth", "burst_multiple", "database_workers"}
        or any(
            not _integer(policy.get(key), number)
            for key, number in (("queue_depth", 32), ("burst_multiple", 5), ("database_workers", 2))
        )
    ):
        reasons.append("LOAD_POLICY_INVALID")
    phases = _mapping(data.get("phases"))
    if phases is None or set(phases) != set(_PHASES):
        reasons.append("PHASE_SET_INVALID")
    evaluated = tuple(
        _phase(name, phases.get(name) if phases is not None else None) for name in _PHASES
    )
    for phase in evaluated:
        reasons.extend(phase.name + ":" + reason for reason in phase.reasons)
    failed = any(phase.status == PerformanceStatus.FAIL for phase in evaluated)
    global_failure = any(
        reason
        in ("REPORT_INVALID", "BENCHMARK_SCOPE_INVALID", "LOAD_POLICY_INVALID", "PHASE_SET_INVALID")
        for reason in reasons
    )
    return PaperPerformanceEvaluation(
        PerformanceStatus.FAIL if failed or global_failure else PerformanceStatus.PASS,
        evaluated,
        tuple(reasons),
    )

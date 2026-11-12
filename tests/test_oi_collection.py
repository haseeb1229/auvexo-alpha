"""Synthetic schedule/START/task/collector proofs; no registration, database or endpoint."""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import psutil
import pytest

from auvexo_alpha.domain.oi_schedule import (
    OIClockProof,
    OICollectionConfig,
    OIStartEnvelope,
    current_slot,
    require_scheduled_start,
    slot_allowed,
    symbol_due,
)
from auvexo_alpha.domain.open_interest import OIManifest, OIRights, oi_dataset_version
from auvexo_alpha.infrastructure import oi_runtime
from auvexo_alpha.infrastructure.oi_collection import OICollectionJob, OIJobStatus
from auvexo_alpha.infrastructure.oi_http import OIReceipt
from auvexo_alpha.infrastructure.public_http import SourceError

NOW = datetime(2026, 10, 30, 12, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def synthetic_w32tm(tmp_path, monkeypatch):
    """Output-parser tests start no process; this tool path is synthetic, never created."""
    path = tmp_path / "synthetic-system" / "w32tm.exe"
    monkeypatch.setattr(oi_runtime, "w32tm_executable", lambda: path)
    return path


def tool(name):
    spec = importlib.util.spec_from_file_location(
        "oi_test_" + name, ROOT / "tools" / (name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configuration(**changes):
    args = dict(
        git_revision="a" * 40,
        code_hash="b" * 64,
        lock_hash="c" * 64,
        preregistration_hash="d" * 64,
        study_id="synthetic-oi",
        clock_source="synthetic-ntp",
    )
    args.update(changes)
    return OICollectionConfig(**args)


def authority(config, at=NOW):
    return OIStartEnvelope(
        owner_authorization_ref="synthetic-owner-ref",
        independent_review_ref="synthetic-review-ref",
        implementation_revision=config.git_revision,
        config_hash=config.content_hash(),
        code_hash=config.code_hash,
        source_hash=config.source.content_hash(),
        rights_hash=config.rights.content_hash(),
        preregistration_hash=config.preregistration_hash,
        issued_at=at - timedelta(days=3, minutes=2),
        owner_start_at=at - timedelta(days=3, minutes=1),
        expires_at=at + timedelta(days=1),
    )


def clock_proof(at=NOW):
    return OIClockProof(
        source="synthetic-ntp",
        inspected_at=at,
        time_since_sync_seconds=2,
        offset_bound_ms=5,
        evidence_hash="e" * 64,
    )


class Clock:
    def __init__(self, at=NOW):
        self.at, self.seconds, self.waits = at, 0.0, []

    def now(self):
        return self.at + timedelta(seconds=self.seconds)

    def mono(self):
        return self.seconds

    def wait(self, delay):
        self.waits.append(delay)
        self.seconds += delay
        return False


class Store:
    def __init__(self, busy=False):
        self.busy = busy
        self.calls, self.manifests, self.studies, self.features, self.quarantines = (
            [],
            {},
            [],
            [],
            [],
        )

    @contextmanager
    def collection_lease(self):
        self.calls.append("lease")
        yield not self.busy

    def append_study(self, study):
        self.calls.append("study")
        self.studies.append(study)

    def checkpoint(self, symbol):
        return self.manifests.get(symbol)

    def publish(self, observation, raw, *, rights, classification, now):
        m = OIManifest(
            dataset_version=oi_dataset_version(observation),
            logical_key=f"ds04-a1:{observation.symbol}:{observation.provider_time_ms}:{observation.parser_version}",
            observation=observation,
            rights=rights,
            raw_relative_path=f"oi/raw/{observation.raw_hash}.raw",
            normalized_relative_path=f"oi/normalized/{observation.content_hash()}.json",
            raw_bytes=len(raw),
            normalized_bytes=len(observation.canonical_bytes()),
            normalized_hash=observation.content_hash(),
            created_at=now,
            processed_at=now,
            classification=classification,
        )
        self.manifests[observation.symbol] = m
        return m

    def scores(self, _):
        return ()

    def forecasts(self, _):
        return ()

    def append_feature(self, feature):
        self.features.append(feature)

    def quarantine(self, body, at, reason):
        assert reason in ("SCHEMA", "PARSER_REJECTED", "SOURCE_REJECTED", "RIGHTS_REJECTED")
        self.quarantines.append((hashlib.sha256(body).hexdigest(), at, reason))


class HTTP:
    def __init__(self, clock, error=None, body=None):
        self.clock, self.error, self.body, self.calls = clock, error, body, []

    def fetch(self, symbol, *, slot_deadline):
        self.calls.append((symbol, self.clock.now(), slot_deadline))
        if self.error:
            raise SourceError(self.error)
        at = self.clock.now()
        body = (
            self.body
            if self.body is not None
            else json.dumps(
                {
                    "openInterest": "101",
                    "symbol": symbol,
                    "time": (at - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(milliseconds=1),
                }
            ).encode()
        )
        return OIReceipt(body, at, at, at)


def job_fixture(config=None, at=NOW, *, ready=lambda: True, busy=False, error=None, body=None):
    config = config or configuration(enabled=True)
    clock, store = Clock(at), Store(busy=busy)
    http = HTTP(clock, error=error, body=body)
    from threading import Event

    cancel = Event()
    job = OICollectionJob(
        config,
        store,
        http,
        cancel=cancel,
        now=clock.now,
        monotonic=clock.mono,
        wait=clock.wait,
        resources_ready=ready,
    )
    return job, store, http, clock, cancel


@pytest.mark.parametrize("hour", range(24))
def test_hourly_schedule_protected_windows_and_symbol_stagger(hour):
    slot = NOW.replace(hour=hour)
    assert slot_allowed(slot) == (hour not in (16, 17, 18))
    assert not slot_allowed(slot + timedelta(seconds=1))
    assert current_slot(slot + timedelta(minutes=12)) == slot
    if hour in (16, 17, 18):
        with pytest.raises(ValueError, match="SCHEDULE_SCOPE"):
            symbol_due(slot, "BTCUSDT")
    else:
        assert symbol_due(slot, "BTCUSDT") == slot
        assert symbol_due(slot, "ETHUSDT") == slot + timedelta(seconds=2)


def test_disabled_no_catchup_and_boundary_deadlines():
    assert configuration().enabled is False
    with pytest.raises(ValueError, match="DISABLED"):
        require_scheduled_start(configuration(), NOW)
    config = configuration(enabled=True)
    assert require_scheduled_start(config, NOW + timedelta(seconds=15)) == NOW
    with pytest.raises(ValueError, match="NO_CATCHUP"):
        require_scheduled_start(config, NOW + timedelta(seconds=15, microseconds=1))
    with pytest.raises(ValueError, match="PROTECTED_WINDOW"):
        require_scheduled_start(config, NOW.replace(hour=16))


@pytest.mark.parametrize(
    "field,bad",
    [
        ("config_hash", "0" * 64),
        ("code_hash", "0" * 64),
        ("source_hash", "0" * 64),
        ("rights_hash", "0" * 64),
        ("preregistration_hash", "0" * 64),
        ("implementation_revision", "0" * 40),
    ],
)
def test_start_envelope_hash_and_scope_bindings(field, bad):
    config = configuration(enabled=True)
    envelope = authority(config)
    envelope.require_start(config, envelope.content_hash(), NOW)
    altered = OIStartEnvelope.model_validate({**envelope.model_dump(mode="python"), field: bad})
    with pytest.raises(ValueError, match="START_AUTHORITY_INVALID"):
        altered.require_start(config, altered.content_hash(), NOW)
    with pytest.raises(ValueError, match="START_AUTHORITY_INVALID"):
        envelope.require_start(config, "0" * 64, NOW)


def test_clock_expiry_future_source_and_rights_failure():
    config = configuration(enabled=True)
    clock_proof().require_trusted(config, NOW + timedelta(seconds=120))
    for at in (NOW - timedelta(microseconds=1), NOW + timedelta(seconds=120, microseconds=1)):
        with pytest.raises(ValueError, match="CLOCK_UNTRUSTED"):
            clock_proof().require_trusted(config, at)
    with pytest.raises(ValueError, match="CLOCK_UNTRUSTED"):
        clock_proof().require_trusted(configuration(enabled=True, clock_source="other"), NOW)
    with pytest.raises(ValueError, match="RIGHTS"):
        require_scheduled_start(config, config.rights.review_due)
    with pytest.raises(ValueError, match="RIGHTS"):
        require_scheduled_start(configuration(enabled=True, rights=OIRights(revoked=True)), NOW)


@pytest.mark.parametrize(
    "source",
    [
        "time.windows.com,0x9",
        "time.windows.com,0x8",
        "time.cloudflare.com,0x8",
        "time-server.example",
        "VM IC Time Synchronization Provider",
        "time-server.example:123 (NTP)",
        " Exact Source Text ",
        "x",
        "x" * 128,
    ],
)
def test_windows_clock_source_type_preserves_config_and_proof_exactly(source):
    config = configuration(clock_source=source)
    proof = OIClockProof.model_validate({**clock_proof().model_dump(), "source": source})
    assert config.clock_source == proof.source == source
    assert OICollectionConfig.model_validate_json(config.canonical_bytes()).clock_source == source
    assert OIClockProof.model_validate_json(proof.canonical_bytes()).source == source
    proof.require_trusted(config, NOW)
    different = configuration(clock_source=source.swapcase())
    with pytest.raises(ValueError, match="OI_CLOCK_UNTRUSTED"):
        proof.require_trusted(different, NOW)


@pytest.mark.parametrize(
    "source",
    [
        "",
        "   ",
        "x" * 129,
        "time.example\x00",
        "time.example\n",
        "time.example\r",
        "time.example\t",
        "time.example\x1b",
        "time.example\x7f",
        "time.example\x85",
        "time.example\u2028",
        "time.example\u2029",
        "time.example\u202e",
        None,
        123,
    ],
)
def test_windows_clock_source_type_refuses_controls_and_invalid_bounds_in_both(source):
    with pytest.raises(ValueError):
        configuration(clock_source=source)
    with pytest.raises(ValueError):
        OIClockProof.model_validate({**clock_proof().model_dump(), "source": source})


@pytest.mark.parametrize(
    "source",
    [
        "time.windows.com,0x9",
        "time.windows.com,0x8",
        "time.cloudflare.com,0x8",
        "time-server.example",
        "VM IC Time Synchronization Provider",
        "time-server.example:123 (NTP)",
    ],
)
def test_native_clock_parser_accepts_exact_safe_source_with_synthetic_trust(
    source, monkeypatch, synthetic_w32tm
):
    output = (
        "Leap Indicator: 0(no warning)\nStratum: 3 (secondary)\n"
        "Time since Last Good Sync Time: 1.2s\nPhase Offset: -0.001s\n"
        "Root Dispersion: 0.002s\nRoot Delay: 0.002s\nSource: " + source + "\n"
    )

    class FixedTime:
        @classmethod
        def now(cls, _timezone):
            return NOW

    monkeypatch.setattr(oi_runtime, "datetime", FixedTime)
    monkeypatch.setattr(
        oi_runtime.subprocess, "run", lambda *_a, **_kw: SimpleNamespace(stdout=output)
    )
    proof = oi_runtime.inspect_clock(source)
    assert proof.source == source and proof.inspected_at == NOW
    assert proof.offset_bound_ms == 4 and proof.time_since_sync_seconds == 2
    proof.require_trusted(configuration(clock_source=source), NOW)
    with pytest.raises(ValueError, match="OI_CLOCK_UNTRUSTED"):
        oi_runtime.inspect_clock(source.swapcase())


def test_start_binds_fixed_database_config_and_refuses_pre_database_hash():
    config = configuration(enabled=True)
    assert config.database_name == "auvexo_dev_oiresearch" and config.database_port == 55433
    payload = json.loads(config.canonical_bytes())
    assert payload.pop("database_name") == "auvexo_dev_oiresearch"
    assert payload.pop("database_port") == 55433
    legacy_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert legacy_hash != config.content_hash()
    envelope = authority(config)
    legacy = OIStartEnvelope.model_validate({**envelope.model_dump(), "config_hash": legacy_hash})
    with pytest.raises(ValueError, match="OI_START_AUTHORITY_INVALID"):
        legacy.require_start(config, legacy.content_hash(), NOW)


@pytest.mark.parametrize(
    "changes",
    [
        {"database_name": "auvexo_dev_oialternate"},
        {"database_name": "auvexo_paper"},
        {"database_name": "auvexo_test_oisynthetic"},
        {"database_port": 55432},
        {"database_port": 55435},
        {"database_port": "55433"},
        {"database_port": True},
        {"database_host": "remote.invalid"},
    ],
)
def test_database_identity_config_is_fixed_and_constructed_start_bypass_denied(changes):
    config = configuration(enabled=True)
    envelope = authority(config)
    with pytest.raises(ValueError):
        configuration(**changes)
    # Even a caller skipping Pydantic validation cannot replay accepted START elsewhere.
    if "database_host" not in changes:
        tampered = config.model_copy(update=changes)
        with pytest.raises(ValueError):
            envelope.require_start(tampered, envelope.content_hash(), NOW)


@pytest.mark.parametrize(
    "case,reason",
    [
        ("disabled", "OI_COLLECTOR_DISABLED"),
        ("missing", "OI_OWNER_START_REQUIRED"),
        ("digest", "OI_START_AUTHORITY_INVALID"),
        ("clock", "OI_CLOCK_UNTRUSTED"),
        ("resource", "OI_RESOURCE_YIELD"),
        ("late", "OI_LATE_NO_CATCHUP"),
        ("protected", "OI_PROTECTED_WINDOW"),
    ],
)
def test_all_preflight_gates_precede_store_or_http(case, reason):
    config = configuration(enabled=case != "disabled")
    at = (
        NOW + timedelta(seconds=16)
        if case == "late"
        else NOW.replace(hour=16)
        if case == "protected"
        else NOW
    )
    job, store, http, _, _ = job_fixture(config, at=at, ready=lambda: case != "resource")
    envelope = None if case == "missing" else authority(config, at)
    digest = "0" * 64 if case == "digest" else envelope.content_hash() if envelope else None
    result = job.run(
        envelope=envelope,
        accepted_start_digest=digest,
        clock=None if case == "clock" else clock_proof(at),
    )
    assert result.code == "BLOCKED" and result.reason == reason
    assert result.forward_days == 0 and not http.calls and not store.calls


def test_cancel_and_single_instance_prevent_network():
    job, store, http, _, cancel = job_fixture()
    envelope = authority(job.config)
    cancel.set()
    result = job.run(
        envelope=envelope, accepted_start_digest=envelope.content_hash(), clock=clock_proof()
    )
    assert result.code == "STOPPED" and not http.calls and not store.calls
    job, store, http, _, _ = job_fixture(busy=True)
    envelope = authority(job.config)
    result = job.run(
        envelope=envelope, accepted_start_digest=envelope.content_hash(), clock=clock_proof()
    )
    assert result.code == "BUSY" and not http.calls and not store.studies


def test_two_symbol_job_staggers_bounds_and_restart_never_catches_up():
    job, store, http, clock, _ = job_fixture()
    envelope = authority(job.config)
    result = job.run(
        envelope=envelope, accepted_start_digest=envelope.content_hash(), clock=clock_proof()
    )
    assert result.code == "COMPLETE" and result.exit_code == 0 and result.forward_days == 0
    assert [row[0] for row in http.calls] == ["BTCUSDT", "ETHUSDT"]
    assert http.calls[1][1] - http.calls[0][1] == timedelta(seconds=2)
    assert all(row[2] == 60 for row in http.calls) and clock.seconds == 2
    assert len(store.manifests) == len(store.features) == 2
    before = len(http.calls)
    repeated = job.run(
        envelope=envelope, accepted_start_digest=envelope.content_hash(), clock=clock_proof()
    )
    assert repeated.code == "COMPLETE" and len(http.calls) == before
    clock.seconds = 16
    late = job.run(
        envelope=envelope, accepted_start_digest=envelope.content_hash(), clock=clock_proof()
    )
    assert late.reason == "OI_LATE_NO_CATCHUP" and len(http.calls) == before


def test_source_failure_and_schema_failure_never_publish_fake_data():
    for error, body in (("OI_COOLDOWN", None), (None, b"{}")):
        job, store, http, _, _ = job_fixture(error=error, body=body)
        envelope = authority(job.config)
        result = job.run(
            envelope=envelope, accepted_start_digest=envelope.content_hash(), clock=clock_proof()
        )
        assert result.code == "SOURCE_UNAVAILABLE" and len(http.calls) == 1
        assert not store.manifests and not store.features
        assert bool(store.quarantines) == (error is None)
        assert result.exit_code == 5 and result.forward_days == 0
        if error is None:
            assert store.quarantines == [(hashlib.sha256(body).hexdigest(), NOW, "PARSER_REJECTED")]
            assert result.reason == "OI_SCHEMA_OR_QUALITY"


def test_resource_recheck_yields_before_second_symbol():
    decisions = iter((True, True, True, False))
    job, store, http, _, _ = job_fixture(ready=lambda: next(decisions))
    envelope = authority(job.config)
    result = job.run(
        envelope=envelope, accepted_start_digest=envelope.content_hash(), clock=clock_proof()
    )
    assert result.reason == "OI_RESOURCE_YIELD" and len(http.calls) == 1


def test_task_xml_is_disabled_limited_interactive_and_has_no_catchup(tmp_path):
    module = tool("oi_task")
    xml = module.task_definition(
        owner="synthetic-owner",
        python=tmp_path / "python.exe",
        script=tmp_path / "tools/run_oi_collection.py",
        config=tmp_path / "config.json",
        start=NOW,
    )
    root = ElementTree.fromstring(xml)
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}

    def text(path):
        return root.find(path, ns).text

    assert text("t:Settings/t:Enabled") == text("t:Triggers/t:TimeTrigger/t:Enabled") == "false"
    assert text("t:Settings/t:MultipleInstancesPolicy") == "IgnoreNew"
    assert text("t:Settings/t:StartWhenAvailable") == text("t:Settings/t:WakeToRun") == "false"
    assert text("t:Settings/t:AllowStartOnDemand") == "false"
    assert text("t:Principals/t:Principal/t:RunLevel") == "LeastPrivilege"
    assert text("t:Principals/t:Principal/t:LogonType") == "InteractiveToken"
    assert text("t:Settings/t:ExecutionTimeLimit") == "PT1M"
    assert text("t:Triggers/t:TimeTrigger/t:Repetition/t:Interval") == "PT1H"
    assert "--scheduled" in text("t:Actions/t:Exec/t:Arguments")
    assert "--accepted-start-hash" not in xml and "Password" not in xml


@pytest.mark.parametrize(
    "owner",
    [
        "",
        "SYSTEM",
        "NT AUTHORITY\\SYSTEM",
        "NT AUTHORITY\\LOCAL SERVICE",
        "NT AUTHORITY\\NETWORK SERVICE",
        "S-1-5-18",
        "S-1-5-19",
        "S-1-5-20",
    ],
)
def test_task_rejects_service_identity_without_registration(owner, tmp_path):
    with pytest.raises(ValueError, match="OI_TASK_CONFIG"):
        tool("oi_task").task_definition(
            owner=owner,
            python=tmp_path / "python",
            script=tmp_path / "script",
            config=tmp_path / "config",
            start=NOW,
        )


def test_cli_default_disabled_denies_before_database_or_clock(tmp_path, monkeypatch, capsys):
    module = tool("run_oi_collection")
    config = tmp_path / "config.json"
    config.write_bytes(configuration().canonical_bytes())
    monkeypatch.setattr(
        module, "create_engine", lambda *_a, **_kw: pytest.fail("database before authority")
    )
    monkeypatch.setattr(module, "inspect_clock", lambda *_: pytest.fail("clock before enabled"))
    monkeypatch.setattr(
        module, "load_oi_database_password", lambda: pytest.fail("secret before enabled")
    )
    monkeypatch.setattr(module.signal, "signal", lambda *_: None)
    monkeypatch.setattr(module.sys, "argv", ["run_oi_collection", "--config", str(config)])
    assert module.main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "BLOCKED" and result["forward_days"] == 0


def test_optional_resource_probe_fails_closed_and_respects_all_budgets(tmp_path, monkeypatch):
    probe = SimpleNamespace(
        virtual_memory=lambda: SimpleNamespace(available=3 * 1024**3),
        cpu_percent=lambda interval: 20,
        disk_usage=lambda _: SimpleNamespace(free=70 * 1024**3),
    )
    monkeypatch.setattr(oi_runtime.importlib, "import_module", lambda _: probe)
    assert oi_runtime.resources_ready(tmp_path)
    for kind in ("memory", "cpu", "disk"):
        changed = SimpleNamespace(**vars(probe))
        if kind == "memory":
            changed.virtual_memory = lambda: SimpleNamespace(available=1)
        if kind == "cpu":
            changed.cpu_percent = lambda interval: 80
        if kind == "disk":
            changed.disk_usage = lambda _: SimpleNamespace(free=1)
        monkeypatch.setattr(oi_runtime.importlib, "import_module", lambda _, p=changed: p)
        assert not oi_runtime.resources_ready(tmp_path)

    def absent(_):
        raise ImportError("synthetic optional capability absent")

    monkeypatch.setattr(oi_runtime.importlib, "import_module", absent)
    assert not oi_runtime.resources_ready(tmp_path)


def test_build_binding_rejects_revision_dirty_code_lock_and_preregistration(tmp_path, monkeypatch):
    (tmp_path / "src/auvexo_alpha").mkdir(parents=True)
    (tmp_path / "tools").mkdir()
    (tmp_path / "docs/phase6").mkdir(parents=True)
    paths = [
        "src/auvexo_alpha/a.py",
        "tools/oi_task.py",
        "tools/run_oi_collection.py",
        "uv.lock",
        "docs/phase6/EXPERIMENT_PREREGISTRATION.md",
    ]
    for path in paths:
        (tmp_path / path).write_text("synthetic fixture", encoding="utf8")

    def digest(path):
        return hashlib.sha256((tmp_path / path).read_bytes()).hexdigest()

    config = configuration(
        code_hash=oi_runtime.oi_code_hash(tmp_path),
        lock_hash=digest("uv.lock"),
        preregistration_hash=digest(paths[-1]),
    )
    commands = []

    def git(output):
        def run(args, **_):
            commands.append(args)
            return config.git_revision + "\n" if "rev-parse" in args else output

        monkeypatch.setattr(oi_runtime.subprocess, "check_output", run)

    # Git resolution and the imported package location have their own real tests below.
    synthetic_git = tmp_path / "outside" / "git"
    monkeypatch.setattr(oi_runtime, "git_executable", lambda _root: synthetic_git)
    monkeypatch.setattr(
        oi_runtime, "loaded_package_directory", lambda: tmp_path / "src/auvexo_alpha"
    )
    git("")
    oi_runtime.require_build(tmp_path, config)
    assert [args[0] for args in commands] == [str(synthetic_git)] * 2
    assert "--untracked-files=all" in commands[1] and "--untracked-files=no" not in commands[1]
    # Untracked files outside the executable scopes are not part of the build.
    git("?? notes/untracked.txt\0?? docs/draft.md\0")
    oi_runtime.require_build(tmp_path, config)
    for output in (
        "?? src/auvexo_alpha/data.json\0",
        "?? src/sitecustomize.pth\0",
        "?? tools/planted.py\0",
        "?? migrations/versions/9999_planted.py\0",
        "?? notes/untracked.txt\0?? Tools/planted.py\0",
        " M docs/tracked.md\0",
        "R  docs/new.md\0docs/old.md\0",
    ):
        git(output)
        with pytest.raises(ValueError, match="BUILD_BINDING"):
            oi_runtime.require_build(tmp_path, config)
    git("")
    for field in ("git_revision", "code_hash", "lock_hash", "preregistration_hash"):
        data = config.model_dump(mode="python")
        data[field] = "0" * (40 if field == "git_revision" else 64)
        with pytest.raises(ValueError, match="BUILD_BINDING"):
            oi_runtime.require_build(tmp_path, OICollectionConfig.model_validate(data))
    git(" M tracked.py")
    with pytest.raises(ValueError, match="BUILD_BINDING"):
        oi_runtime.require_build(tmp_path, config)
    # A stale installed copy is refused even when the checkout itself is exact.
    git("")
    oi_runtime.require_build(tmp_path, config)
    stale = tmp_path / "site-packages/auvexo_alpha"
    stale.mkdir(parents=True)
    (stale / "a.py").write_text("synthetic stale copy", encoding="utf8")
    monkeypatch.setattr(oi_runtime, "loaded_package_directory", lambda: stale)
    with pytest.raises(ValueError, match="BUILD_BINDING"):
        oi_runtime.require_build(tmp_path, config)


def test_clock_inspection_is_read_only_and_ambiguous_output_denies(monkeypatch, synthetic_w32tm):
    valid = (
        "Leap Indicator: 0(no warning)\nStratum: 3 (secondary)\n"
        "Time since Last Good Sync Time: 1.2s\nPhase Offset: -0.001s\n"
        "Root Dispersion: 0.002s\nRoot Delay: 0.002s\nSource: synthetic-ntp\n"
    )
    calls = []

    def result(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=valid)

    monkeypatch.setattr(oi_runtime.subprocess, "run", result)
    proof = oi_runtime.inspect_clock("synthetic-ntp")
    assert proof.offset_bound_ms == 4 and proof.time_since_sync_seconds == 2
    # Never the bare name: the gate itself supplies the absolute tool path.
    assert calls == [[str(synthetic_w32tm), "/query", "/status", "/verbose"]]
    for bad in (
        valid.replace("Source:", "Localized Source:"),
        valid.replace("0.002s", "2s"),
        valid.replace("0(no warning)", "3(no sync)"),
        valid.replace("Root Delay: 0.002s", "Root Delay: -0.002s"),
    ):
        monkeypatch.setattr(
            oi_runtime.subprocess,
            "run",
            lambda *_a, value=bad, **_kw: SimpleNamespace(stdout=value),
        )
        with pytest.raises(ValueError, match="CLOCK_UNTRUSTED"):
            oi_runtime.inspect_clock("synthetic-ntp")


@pytest.mark.parametrize(
    "code,exit_code",
    [
        ("COMPLETE", 0),
        ("BLOCKED", 2),
        ("BUSY", 3),
        ("STOPPED", 4),
        ("SOURCE_UNAVAILABLE", 5),
        ("LEDGER_REVIEW_REQUIRED", 6),
    ],
)
def test_status_codes_never_create_forward_credit(code, exit_code):
    result = OIJobStatus(code, "SYNTHETIC")
    assert result.exit_code == exit_code and result.forward_days == 0
    assert result.research_failures == ()
    if code == "COMPLETE":
        # A recorded research failure can never be reported as a clean exit 0.
        with pytest.raises(ValueError, match="OI_STATUS_HIDES_RESEARCH_FAILURE"):
            OIJobStatus(code, "SYNTHETIC", research_failures=("BTCUSDT:SYNTHETIC",))
    else:
        flagged = OIJobStatus(code, "SYNTHETIC", research_failures=("BTCUSDT:SYNTHETIC",))
        assert flagged.exit_code == exit_code != 0


def test_authority_expiry_during_symbol_stagger_prevents_second_request():
    job, store, http, _, _ = job_fixture()
    base = authority(job.config)
    envelope = OIStartEnvelope.model_validate(
        {**base.model_dump(mode="python"), "expires_at": NOW + timedelta(seconds=1)}
    )
    result = job.run(
        envelope=envelope, accepted_start_digest=envelope.content_hash(), clock=clock_proof()
    )
    assert result.code == "BLOCKED" and result.reason == "OI_RUNTIME_AUTHORITY_OR_CLOCK_INVALID"
    assert [call[0] for call in http.calls] == ["BTCUSDT"]


@pytest.mark.parametrize(
    "change,reason",
    [
        ("cancel", "OI_STOPPED"),
        ("deadline", "OI_SLOT_DEADLINE"),
        ("clock", "OI_RUNTIME_AUTHORITY_OR_CLOCK_INVALID"),
    ],
)
def test_interruption_during_wait_never_reaches_http(change, reason):
    job, store, http, clock, cancel = job_fixture()
    envelope = authority(job.config)

    def interrupted_wait(delay):
        if change == "cancel":
            cancel.set()
        elif change == "deadline":
            clock.seconds = 61
        else:
            clock.at -= timedelta(seconds=1)
        return False

    job.wait = interrupted_wait
    result = job.run(
        envelope=envelope, accepted_start_digest=envelope.content_hash(), clock=clock_proof()
    )
    assert result.reason == reason and not http.calls and not store.manifests


def test_explicit_oi_pg_override_never_uses_operational_port(monkeypatch):
    from oi_pg_helpers import oi_test_server

    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("TEST_PG_PORT", "55432")
    monkeypatch.setenv("OI_TEST_PG_PORT", "55440")
    with oi_test_server() as port:
        assert port == 55440
    assert os.environ["TEST_PG_PORT"] == "55432"


@pytest.mark.parametrize("variable", ["OI_TEST_PG_PORT", "TEST_PG_PORT"])
def test_local_oi_tests_never_reach_the_fixed_production_runtime_port(variable, monkeypatch):
    from oi_pg_helpers import OI_RUNTIME_PORT, oi_test_server

    assert OI_RUNTIME_PORT == 55433 == configuration().database_port
    monkeypatch.delenv("OI_TEST_PG_PORT", raising=False)
    monkeypatch.setenv("TEST_PG_PORT", "55432")
    monkeypatch.setenv(variable, "55433")
    for marker in (None, "false", "TRUE", "1"):
        if marker is None:
            monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        else:
            monkeypatch.setenv("GITHUB_ACTIONS", marker)
        with pytest.raises(ValueError, match="OI_TEST_PORT_INVALID"):
            with oi_test_server():
                pytest.fail("a local test must never reach the production OI runtime")
    # Only the disposable CI container may listen on that port.
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with oi_test_server() as port:
        assert port == 55433


@pytest.mark.parametrize(
    "value",
    [
        "55432",
        "55433",
        "0",
        "65536",
        "True",
        "55433.0",
        " 55433",
        "-55433",
        "\u0665\u0665\u0664\u0663\u0663",
    ],
)
def test_oi_pg_override_invalid_is_not_fallback(value, monkeypatch):
    from oi_pg_helpers import oi_test_server

    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("TEST_PG_PORT", "55440")
    monkeypatch.setenv("OI_TEST_PG_PORT", value)
    with pytest.raises(ValueError, match="OI_TEST_PORT_INVALID"):
        with oi_test_server():
            pytest.fail("invalid override must not fall back to another endpoint")


def test_task_optional_reviewed_start_inputs_remain_disabled(tmp_path):
    module = tool("oi_task")
    args = dict(
        owner="synthetic-owner",
        python=tmp_path / "python.exe",
        script=tmp_path / "tools/run_oi_collection.py",
        config=tmp_path / "config.json",
        start=NOW,
    )
    xml = module.task_definition(
        **args,
        start_envelope=tmp_path / "synthetic-start.json",
        accepted_start_hash="a" * 64,
    )
    root = ElementTree.fromstring(xml)
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    arguments = root.find("t:Actions/t:Exec/t:Arguments", ns).text
    assert "--start-envelope" in arguments and "--accepted-start-hash" in arguments
    assert "--database" not in arguments and "--port" not in arguments
    assert root.find("t:Settings/t:Enabled", ns).text == "false"
    assert root.find("t:Triggers/t:TimeTrigger/t:Enabled", ns).text == "false"
    for changes in (
        {"start_envelope": tmp_path / "synthetic-start.json"},
        {"accepted_start_hash": "a" * 64},
        {"start_envelope": Path("relative.json"), "accepted_start_hash": "a" * 64},
        {"start_envelope": tmp_path / "synthetic-start.json", "accepted_start_hash": "invalid"},
    ):
        with pytest.raises(ValueError, match="OI_TASK_CONFIG"):
            module.task_definition(**args, **changes)
    # Database identity belongs only to the config accepted by START, never the task.
    for changes in (
        {"database": "auvexo_dev_oiresearch"},
        {"database": "auvexo_dev_oifuture"},
        {"database": "auvexo_paper"},
        {"port": 55433},
        {"port": 55432},
    ):
        with pytest.raises(TypeError):
            module.task_definition(**args, **changes)


@pytest.mark.parametrize(
    "boundary,reason",
    [
        ("before_t0", "OI_STUDY_NOT_DUE"),
        ("at_end", "OI_STUDY_WINDOW_COMPLETE"),
        ("after_end", "OI_STUDY_WINDOW_COMPLETE"),
    ],
)
def test_study_calendar_bounds_precede_store_and_source(boundary, reason, monkeypatch):
    from auvexo_alpha.application.oi_research import OIStudyWindow

    if boundary == "before_t0":
        monkeypatch.setattr(OIStudyWindow, "t0", property(lambda self: NOW + timedelta(days=1)))
    else:
        end = NOW if boundary == "at_end" else NOW - timedelta(hours=1)
        monkeypatch.setattr(OIStudyWindow, "evaluation_end", property(lambda self: end))
    job, store, http, _, _ = job_fixture()
    envelope = authority(job.config)
    result = job.run(
        envelope=envelope, accepted_start_digest=envelope.content_hash(), clock=clock_proof()
    )
    assert result.code == "BLOCKED" and result.reason == reason and result.forward_days == 0
    assert not http.calls and not store.calls and not store.studies and not store.manifests


@pytest.mark.parametrize(
    "offset", [timedelta(minutes=57), timedelta(seconds=1), timedelta(microseconds=1)]
)
def test_task_trigger_requires_exact_hour_alignment(tmp_path, offset):
    with pytest.raises(ValueError, match="OI_TASK_CONFIG"):
        tool("oi_task").task_definition(
            owner="synthetic-owner",
            python=tmp_path / "python.exe",
            script=tmp_path / "tools/run_oi_collection.py",
            config=tmp_path / "config.json",
            start=NOW + offset,
        )


@pytest.mark.parametrize(
    "at",
    [NOW.replace(hour=16), NOW.replace(hour=17), NOW.replace(hour=18), NOW + timedelta(seconds=16)],
)
def test_cli_schedule_denies_before_build_clock_or_database(at, tmp_path, monkeypatch, capsys):
    module = tool("run_oi_collection")
    config = configuration(enabled=True)
    config_path = tmp_path / "synthetic-config.json"
    config_path.write_bytes(config.canonical_bytes())
    envelope = authority(config, at)
    envelope_path = tmp_path / "synthetic-envelope.json"
    envelope_path.write_bytes(envelope.canonical_bytes())

    class FixedTime:
        @classmethod
        def now(cls, _timezone):
            return at

    monkeypatch.setattr(module, "datetime", FixedTime)
    monkeypatch.setattr(
        module, "require_build", lambda *_: pytest.fail("build before schedule gate")
    )
    monkeypatch.setattr(
        module, "inspect_clock", lambda *_: pytest.fail("clock before schedule gate")
    )
    monkeypatch.setattr(
        module, "create_engine", lambda *_a, **_kw: pytest.fail("database before schedule gate")
    )
    monkeypatch.setattr(
        module, "load_oi_database_password", lambda: pytest.fail("secret before schedule gate")
    )
    monkeypatch.setattr(module.signal, "signal", lambda *_: None)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "run_oi_collection",
            "--config",
            str(config_path),
            "--scheduled",
            "--start-envelope",
            str(envelope_path),
            "--accepted-start-hash",
            envelope.content_hash(),
        ],
    )
    assert module.main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "BLOCKED" and result["forward_days"] == 0


def test_cli_uses_dedicated_oi_managed_root_not_engineering_cache(tmp_path, monkeypatch, capsys):
    module = tool("run_oi_collection")
    config = configuration(enabled=True)
    config_path = tmp_path / "synthetic-config.json"
    config_path.write_bytes(config.canonical_bytes())
    envelope = authority(config)
    envelope_path = tmp_path / "synthetic-envelope.json"
    envelope_path.write_bytes(envelope.canonical_bytes())
    captured = {}

    class FixedTime:
        @classmethod
        def now(cls, _timezone):
            return NOW

    class FakeStore:
        def __init__(self, engine, root, managed_root, *, review_authority=None):
            assert review_authority is None
            captured.update(root=root, managed_root=managed_root)

        def load_transport_state(self, _now):
            return object()

        def save_transport_state(self, _state):
            pytest.fail("no actual persistence in CLI path fixture")

    class FakeJob:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self, **_kwargs):
            return OIJobStatus("COMPLETE", "SYNTHETIC_NO_COLLECTION")

    monkeypatch.setattr(module, "datetime", FixedTime)
    monkeypatch.setattr(module, "require_build", lambda *_: None)
    monkeypatch.setattr(module, "inspect_clock", lambda *_: clock_proof())
    monkeypatch.setattr(
        module, "create_engine", lambda *_a, **_kw: SimpleNamespace(dispose=lambda: None)
    )
    monkeypatch.setattr(module, "OIStore", FakeStore)
    monkeypatch.setattr(module, "OIHTTP", lambda *_a, **_kw: object())
    monkeypatch.setattr(module, "OICollectionJob", FakeJob)
    monkeypatch.setattr(module.signal, "signal", lambda *_: None)
    monkeypatch.setattr(module, "load_oi_database_password", lambda: "SYNTHETIC_ONLY_" + "a" * 40)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "run_oi_collection",
            "--config",
            str(config_path),
            "--scheduled",
            "--start-envelope",
            str(envelope_path),
            "--accepted-start-hash",
            envelope.content_hash(),
        ],
    )
    assert module.main() == 0
    assert captured["managed_root"] == ROOT / ".local/phase6/oi-managed"
    assert captured["root"] == captured["managed_root"] / "artifacts"
    assert json.loads(capsys.readouterr().out)["forward_days"] == 0


def test_task_review_chain_arguments_are_external_and_still_disabled(tmp_path):
    module = tool("oi_task")
    params = dict(
        owner="synthetic-owner",
        python=tmp_path / "python.exe",
        script=tmp_path / "tools/run_oi_collection.py",
        config=tmp_path / "config.json",
        start=NOW,
    )
    xml = module.task_definition(
        **params, review_chain=tmp_path / "review.json", accepted_review_hashes=("a" * 64, "b" * 64)
    )
    root = ElementTree.fromstring(xml)
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    args = root.find("t:Actions/t:Exec/t:Arguments", ns).text
    assert args.count("--accepted-review-hash") == 2 and "--review-chain" in args
    assert root.find("t:Settings/t:Enabled", ns).text == "false"
    for changes in (
        {"review_chain": tmp_path / "review.json"},
        {"accepted_review_hashes": ("a" * 64,)},
        {"review_chain": tmp_path / "review.json", "accepted_review_hashes": ("bad",)},
        {"review_chain": tmp_path / "review.json", "accepted_review_hashes": ("a" * 64, "a" * 64)},
    ):
        with pytest.raises(ValueError, match="OI_TASK_REVIEW_CHAIN_CONFIG"):
            module.task_definition(**params, **changes)


def test_receipt_after_owner_expiry_is_quarantined_without_manifest():
    from auvexo_alpha.domain.oi_schedule import OIStartEnvelope

    job, store, http, clock, _ = job_fixture()
    payload = authority(job.config).model_dump(mode="python")
    payload["expires_at"] = NOW + timedelta(seconds=1)
    envelope = OIStartEnvelope.model_validate(payload)
    fetch = http.fetch

    def delayed(symbol, **kwargs):
        result = fetch(symbol, **kwargs)
        clock.seconds += 2
        return result

    http.fetch = delayed
    result = job.run(
        envelope=envelope, accepted_start_digest=envelope.content_hash(), clock=clock_proof()
    )
    assert result.code == "BLOCKED" and result.reason == "OI_RECEIPT_ADMISSION_EXPIRED"
    assert store.quarantines[-1][2] == "RIGHTS_REJECTED" and not store.manifests


@pytest.mark.parametrize(
    "source",
    [
        "Local CMOS Clock",
        "Free-running System Clock",
        "local clock",
        "localhost",
        "127.0.0.1",
        "::1",
    ],
)
def test_untrusted_local_clock_source_cannot_be_declared_trusted(
    source, monkeypatch, synthetic_w32tm
):
    output = (
        "Leap Indicator: 0(no warning)\nStratum: 1 (primary)\n"
        "Time since Last Good Sync Time: 1s\nPhase Offset: 0s\n"
        "Root Dispersion: 0s\nRoot Delay: 0s\nSource: " + source + "\n"
    )
    monkeypatch.setattr(
        oi_runtime.subprocess, "run", lambda *_a, **_kw: SimpleNamespace(stdout=output)
    )
    with pytest.raises(ValueError, match="OI_CLOCK_UNTRUSTED"):
        oi_runtime.inspect_clock(source)


def _check_sensitive(condition):
    if not condition:
        raise AssertionError("synthetic secret/output assertion failed")


def cli_authorized_fixture(tmp_path, monkeypatch, *, at=NOW, config=None):
    """No real OS secret, DB, clock process, endpoint or activation in this CLI fixture."""
    module = tool("run_oi_collection")
    config = config or configuration(enabled=True)
    config_path = tmp_path / "synthetic-config.json"
    config_path.write_bytes(config.canonical_bytes())
    envelope = authority(config, at)
    envelope_path = tmp_path / "synthetic-start.json"
    envelope_path.write_bytes(envelope.canonical_bytes())

    class FixedTime:
        @classmethod
        def now(cls, _timezone):
            return at

    monkeypatch.setattr(module, "datetime", FixedTime)
    monkeypatch.setattr(module.signal, "signal", lambda *_: None)
    monkeypatch.setattr(module, "require_build", lambda *_: None)
    monkeypatch.setattr(module, "inspect_clock", lambda *_: clock_proof(at))
    argv = [
        "run_oi_collection",
        "--config",
        str(config_path),
        "--scheduled",
        "--start-envelope",
        str(envelope_path),
        "--accepted-start-hash",
        envelope.content_hash(),
    ]
    monkeypatch.setattr(module.sys, "argv", argv)
    return module, config, config_path, envelope, envelope_path, argv


@pytest.mark.parametrize(
    "case",
    [
        "disabled",
        "manual",
        "protected",
        "late",
        "rights_expired",
        "config_invalid",
        "start_missing",
        "start_invalid",
        "build_invalid",
        "clock_inspection_failed",
        "clock_untrusted",
        "database_foreign",
        "database_port_invalid",
        "database_operational_port",
        "review_chain_invalid",
    ],
)
def test_cli_every_early_gate_prevents_persistent_secret_decryption(
    case, tmp_path, monkeypatch, capsys
):
    at = (
        NOW.replace(hour=16)
        if case == "protected"
        else NOW + timedelta(seconds=16)
        if case == "late"
        else datetime(2026, 11, 27, 12, tzinfo=UTC)
        if case == "rights_expired"
        else NOW
    )
    config = configuration(enabled=case != "disabled")
    module, _, config_path, envelope, envelope_path, argv = cli_authorized_fixture(
        tmp_path, monkeypatch, at=at, config=config
    )
    if case == "manual":
        argv.remove("--scheduled")
    elif case == "config_invalid":
        config_path.write_bytes(b'{"unknown":"SYNTHETIC_SENSITIVE_FAILURE"}')
    elif case == "start_missing":
        argv.remove("--start-envelope")
        argv.remove(str(envelope_path))
    elif case == "start_invalid":
        argv[-1] = "0" * 64
    elif case == "build_invalid":

        def bad_build(*_):
            raise ValueError("SYNTHETIC_SENSITIVE_FAILURE")

        monkeypatch.setattr(module, "require_build", bad_build)
    elif case == "clock_inspection_failed":

        def bad_clock(*_):
            raise ValueError("SYNTHETIC_SENSITIVE_FAILURE")

        monkeypatch.setattr(module, "inspect_clock", bad_clock)
    elif case == "clock_untrusted":
        monkeypatch.setattr(
            module, "inspect_clock", lambda *_: clock_proof(at - timedelta(seconds=121))
        )
    elif case == "database_foreign":
        argv.extend(["--database", "auvexo_paper"])
    elif case == "database_port_invalid":
        argv.extend(["--port", "0"])
    elif case == "database_operational_port":
        argv.extend(["--port", "55432"])
    elif case == "review_chain_invalid":
        path = tmp_path / "synthetic-unaccepted-review.json"
        path.write_bytes(b"[]")
        argv.extend(["--review-chain", str(path)])
    monkeypatch.setattr(
        module, "load_oi_database_password", lambda: pytest.fail("secret before gates")
    )
    monkeypatch.setattr(module, "create_engine", lambda *_a, **_kw: pytest.fail("DB before gates"))
    status = module.main()
    output = capsys.readouterr()
    _check_sensitive(
        not output.err
        and "SYNTHETIC_SENSITIVE" not in output.out
        and "IGNORED_ENV" not in output.out
    )
    _check_sensitive(
        not output.err
        and "SYNTHETIC_SENSITIVE" not in output.out
        and "IGNORED_ENV" not in output.out
    )
    assert status == 2
    assert json.loads(output.out) == {
        "status": "BLOCKED",
        "reason": "OI_PREFLIGHT_OR_PERSISTENCE_FAILED",
        "forward_days": 0,
    }
    _check_sensitive(not output.err and "SYNTHETIC_SENSITIVE_FAILURE" not in output.out)


def test_cli_os_secret_decrypts_after_clock_and_before_first_database_connection(
    tmp_path,
    monkeypatch,
    capsys,
):
    module, config, _, _, _, _ = cli_authorized_fixture(tmp_path, monkeypatch)
    calls = []
    password = "SYNTHETIC_ONLY_" + "q" * 40
    monkeypatch.setenv("AUVEXO_OI_DB_PASSWORD", "IGNORED_ENV_ONLY_" + "z" * 40)

    def built(*_):
        calls.append("build")

    def inspected(*_):
        calls.append("clock")
        return clock_proof()

    def secret():
        calls.append("secret")
        return password

    class FakeStore:
        def __init__(self, engine, root, managed_root, *, review_authority=None):
            calls.append("store")

        def load_transport_state(self, _):
            return object()

        def save_transport_state(self, _):
            pytest.fail("no real persistence")

    class FakeJob:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self, **_kwargs):
            calls.append("job")
            return OIJobStatus("COMPLETE", "SYNTHETIC_NO_COLLECTION")

    def engine(url, **kwargs):
        _check_sensitive(url.password == password)
        assert (
            url.username == "auvexo_data_writer"
            and url.host == "127.0.0.1"
            and url.port == config.database_port == 55433
            and url.database == config.database_name == "auvexo_dev_oiresearch"
        )
        assert kwargs["hide_parameters"] is True
        calls.append("connect")
        return SimpleNamespace(dispose=lambda: calls.append("dispose"))

    monkeypatch.setattr(module, "require_build", built)
    monkeypatch.setattr(module, "inspect_clock", inspected)
    monkeypatch.setattr(module, "load_oi_database_password", secret)
    monkeypatch.setattr(module, "create_engine", engine)
    monkeypatch.setattr(module, "OIStore", FakeStore)
    monkeypatch.setattr(module, "OIHTTP", lambda *_a, **_kw: object())
    monkeypatch.setattr(module, "OICollectionJob", FakeJob)
    status = module.main()
    output = capsys.readouterr()
    _check_sensitive(
        not output.err and password not in output.out and "IGNORED_ENV_ONLY" not in output.out
    )
    assert status == 0
    assert calls == ["build", "clock", "secret", "connect", "store", "job", "dispose"]
    assert json.loads(output.out)["forward_days"] == 0


def test_cli_secret_failure_is_generic_no_environment_fallback_or_connection(
    tmp_path,
    monkeypatch,
    capsys,
):
    module, _, _, _, _, _ = cli_authorized_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("AUVEXO_OI_DB_PASSWORD", "IGNORED_ENV_ONLY_" + "z" * 40)

    def unavailable():
        raise ValueError("SYNTHETIC_SENSITIVE_DPAPI_FAILURE_" + "q" * 40)

    monkeypatch.setattr(module, "load_oi_database_password", unavailable)
    monkeypatch.setattr(
        module, "create_engine", lambda *_a, **_kw: pytest.fail("no secret fallback")
    )
    status = module.main()
    output = capsys.readouterr()
    _check_sensitive(
        not output.err
        and "SYNTHETIC_SENSITIVE" not in output.out
        and "IGNORED_ENV" not in output.out
    )
    assert status == 2
    assert json.loads(output.out) == {
        "status": "BLOCKED",
        "reason": "OI_PREFLIGHT_OR_PERSISTENCE_FAILED",
        "forward_days": 0,
    }


def test_collector_source_has_no_environment_or_plaintext_password_argument():
    source = (ROOT / "tools/run_oi_collection.py").read_text(encoding="utf8")
    assert "AUVEXO_OI_DB_PASSWORD" not in source and "os.environ" not in source
    assert 'add_argument("--password"' not in source
    assert 'add_argument("--secret"' not in source


@pytest.mark.parametrize("option", ["--password", "--port"])
def test_cli_unrecognized_secret_argument_or_invalid_type_is_redacted(
    option,
    tmp_path,
    monkeypatch,
    capsys,
):
    module, _, _, _, _, argv = cli_authorized_fixture(tmp_path, monkeypatch)
    argv.extend([option, "SYNTHETIC_SENSITIVE_MUST_NOT_ECHO_" + "x" * 40])
    monkeypatch.setattr(
        module, "load_oi_database_password", lambda: pytest.fail("secret before parse")
    )
    monkeypatch.setattr(module, "create_engine", lambda *_a, **_kw: pytest.fail("DB before parse"))
    status = module.main()
    output = capsys.readouterr()
    _check_sensitive(not output.err and "SYNTHETIC_SENSITIVE" not in output.out)
    assert status == 2
    assert json.loads(output.out)["reason"] == "OI_PREFLIGHT_OR_PERSISTENCE_FAILED"
    _check_sensitive(not output.err and "SYNTHETIC_SENSITIVE" not in output.out)


@pytest.mark.parametrize("gate", ["late", "start_expired", "rights_expired"])
@pytest.mark.parametrize("inspection", ["build", "clock"])
def test_cli_revalidates_time_sensitive_authority_before_secret_decryption(
    gate,
    inspection,
    tmp_path,
    monkeypatch,
    capsys,
):
    initial = datetime(2026, 11, 26, 23, tzinfo=UTC) if gate == "rights_expired" else NOW
    module, config, _, envelope, envelope_path, argv = cli_authorized_fixture(
        tmp_path, monkeypatch, at=initial
    )
    if gate == "start_expired":
        envelope = OIStartEnvelope.model_validate(
            {**envelope.model_dump(mode="python"), "expires_at": initial + timedelta(seconds=1)}
        )
    elif gate == "rights_expired":
        envelope = OIStartEnvelope.model_validate(
            {**envelope.model_dump(mode="python"), "expires_at": config.rights.review_due}
        )
    envelope_path.write_bytes(envelope.canonical_bytes())
    argv[-1] = envelope.content_hash()
    clock = {"at": initial}
    calls = []

    class FreshTime:
        @classmethod
        def now(cls, _timezone):
            return clock["at"]

    def advance():
        clock["at"] += (
            timedelta(hours=1)
            if gate == "rights_expired"
            else timedelta(seconds=16)
            if gate == "late"
            else timedelta(seconds=2)
        )

    def build(*_):
        calls.append("build")
        if inspection == "build":
            advance()

    def inspect(*_):
        calls.append("clock")
        if inspection == "clock":
            advance()
        return clock_proof(clock["at"])

    monkeypatch.setattr(module, "datetime", FreshTime)
    monkeypatch.setattr(module, "require_build", build)
    monkeypatch.setattr(module, "inspect_clock", inspect)
    monkeypatch.setattr(
        module, "load_oi_database_password", lambda: pytest.fail("expired secret gate")
    )
    monkeypatch.setattr(module, "create_engine", lambda *_a, **_kw: pytest.fail("expired DB gate"))
    status = module.main()
    output = capsys.readouterr()
    _check_sensitive(not output.err and "SYNTHETIC_SENSITIVE" not in output.out)
    assert status == 2 and calls == ["build", "clock"]
    assert json.loads(output.out) == {
        "status": "BLOCKED",
        "reason": "OI_PREFLIGHT_OR_PERSISTENCE_FAILED",
        "forward_days": 0,
    }


def plant(directory, name):
    """A fake executable that these tests only ever locate; it is never executed."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (name + (".exe" if os.name == "nt" else ""))
    path.write_bytes(b"SYNTHETIC_PLANTED_NEVER_EXECUTED")
    path.chmod(0o755)
    return path


def forbid_processes(monkeypatch):
    for name in ("run", "check_output", "Popen"):
        monkeypatch.setattr(
            oi_runtime.subprocess,
            name,
            lambda *_a, **_kw: pytest.fail("a planted executable must never be started"),
        )


def launch_directories(tmp_path, monkeypatch):
    root, launch, outside = (tmp_path / name for name in ("checkout", "launch", "outside"))
    for directory in (root, launch, outside):
        directory.mkdir()
    monkeypatch.chdir(launch)
    forbid_processes(monkeypatch)
    return root, launch, outside


@pytest.mark.parametrize(
    "location",
    ["current_directory", "relative_path_entry", "checkout_root", "checkout_environment"],
)
def test_build_gate_refuses_git_supplied_by_the_checkout_or_launch_directory(
    location, tmp_path, monkeypatch
):
    root, launch, outside = launch_directories(tmp_path, monkeypatch)
    if location == "current_directory":
        plant(launch, "git")
        # Windows searches the current directory implicitly, before any PATH entry.
        monkeypatch.setenv("PATH", str(outside) if os.name == "nt" else os.curdir)
    elif location == "relative_path_entry":
        plant(launch / "bin", "git")
        monkeypatch.setenv("PATH", "bin")
    elif location == "checkout_root":
        plant(root, "git")
        monkeypatch.setenv("PATH", str(root))
    else:
        scripts = root / ".venv" / "Scripts"
        plant(scripts, "git")
        monkeypatch.setenv("PATH", os.pathsep.join((str(scripts), str(outside))))
    with pytest.raises(ValueError, match="^OI_BUILD_BINDING$"):
        oi_runtime.git_executable(root)
    # The whole gate refuses before any process, so the planted file cannot answer it.
    with pytest.raises(ValueError, match="^OI_BUILD_BINDING$"):
        oi_runtime.require_build(root, configuration())


def test_build_gate_resolves_one_absolute_git_outside_checkout_or_refuses_absence(
    tmp_path, monkeypatch
):
    root, _, outside = launch_directories(tmp_path, monkeypatch)
    monkeypatch.setenv("PATH", str(outside))
    with pytest.raises(ValueError, match="^OI_BUILD_BINDING$"):
        oi_runtime.git_executable(root)
    planted = plant(outside, "git")
    resolved = oi_runtime.git_executable(root)
    assert resolved.is_absolute() and resolved == planted.resolve()
    assert not resolved.is_relative_to(root.resolve())
    assert not resolved.is_relative_to(Path.cwd().resolve())


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows system directory API")
def test_clock_tool_is_native_system32_never_path_cwd_or_environment(tmp_path, monkeypatch):
    genuine = Path(os.environ["SYSTEMROOT"]) / "System32" / "w32tm.exe"
    # Planted look-alikes everywhere a bare name or an environment variable would lead.
    plant(tmp_path, "w32tm")
    plant(tmp_path / "fake-root" / "System32", "w32tm")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("SYSTEMROOT", str(tmp_path / "fake-root"))
    monkeypatch.setenv("WINDIR", str(tmp_path / "fake-root"))
    tool = oi_runtime.w32tm_executable()
    assert tool.is_absolute() and tool.is_file()
    assert os.path.normcase(str(tool)) == os.path.normcase(str(genuine))
    assert not tool.resolve().is_relative_to(tmp_path.resolve())
    calls = []
    output = (
        "Leap Indicator: 0(no warning)\nStratum: 3 (secondary)\n"
        "Time since Last Good Sync Time: 1.2s\nPhase Offset: -0.001s\n"
        "Root Dispersion: 0.002s\nRoot Delay: 0.002s\nSource: synthetic-ntp\n"
    )
    monkeypatch.setattr(
        oi_runtime.subprocess,
        "run",
        lambda args, **_kw: calls.append(args) or SimpleNamespace(stdout=output),
    )
    oi_runtime.inspect_clock("synthetic-ntp")
    assert calls == [[str(tool), "/query", "/status", "/verbose"]]


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows refusal")
def test_clock_inspection_refuses_off_windows_before_any_process(monkeypatch):
    forbid_processes(monkeypatch)
    with pytest.raises(ValueError, match="^OI_CLOCK_UNTRUSTED$"):
        oi_runtime.w32tm_executable()
    with pytest.raises(ValueError, match="^OI_CLOCK_UNTRUSTED$"):
        oi_runtime.inspect_clock("synthetic-ntp")


@pytest.mark.parametrize(
    "change", ["identical", "modified", "extra", "extra_nested", "missing", "no_checkout_source"]
)
def test_build_gate_proves_the_imported_package_is_the_hashed_tree(change, tmp_path):
    files = {"__init__.py": "", "domain/a.py": "A = 1\n", "infrastructure/b.py": "B = 2\n"}
    root = tmp_path / "checkout"
    installed = tmp_path / "environment" / "site-packages" / "auvexo_alpha"
    for base in (root / "src" / "auvexo_alpha", installed):
        if base != installed and change == "no_checkout_source":
            continue
        for name, content in files.items():
            (base / name).parent.mkdir(parents=True, exist_ok=True)
            (base / name).write_text(content, encoding="utf8")
    if change == "modified":
        (installed / "domain/a.py").write_text("A = 2\n", encoding="utf8")
    elif change == "extra":
        (installed / "stale_module.py").write_text("STALE = True\n", encoding="utf8")
    elif change == "extra_nested":
        (installed / "infrastructure/old.py").write_text("OLD = True\n", encoding="utf8")
    elif change == "missing":
        (installed / "infrastructure/b.py").unlink()
    if change == "identical":
        oi_runtime.require_imported_tree(root, installed)
        return
    with pytest.raises(ValueError, match="^OI_BUILD_BINDING$"):
        oi_runtime.require_imported_tree(root, installed)


def test_this_environment_executes_exactly_the_checkout_package():
    package = oi_runtime.loaded_package_directory()
    assert package.is_absolute() and (package / "infrastructure" / "oi_runtime.py").is_file()
    assert package == Path(oi_runtime.__file__).resolve().parents[1]
    oi_runtime.require_imported_tree(ROOT, package)


def cli_fake_runtime(module, monkeypatch, run):
    """Authorized CLI path with no secret, database, endpoint or real job."""

    class FakeStore:
        def __init__(self, engine, root, managed_root, *, review_authority=None):
            pass

        def load_transport_state(self, _now):
            return object()

        def save_transport_state(self, _state):
            pytest.fail("no persistence in a CLI fixture")

    class FakeJob:
        def __init__(self, *_args, **kwargs):
            self.resources_ready = kwargs["resources_ready"]

        def run(self, **_kwargs):
            return run(self)

    monkeypatch.setattr(module, "load_oi_database_password", lambda: "SYNTHETIC_ONLY_" + "a" * 40)
    monkeypatch.setattr(
        module, "create_engine", lambda *_a, **_kw: SimpleNamespace(dispose=lambda: None)
    )
    monkeypatch.setattr(module, "OIStore", FakeStore)
    monkeypatch.setattr(module, "OIHTTP", lambda *_a, **_kw: object())
    monkeypatch.setattr(module, "OICollectionJob", FakeJob)


@pytest.mark.parametrize(
    "case,error_class",
    [
        ("git_failed", "CalledProcessError"),
        ("git_hung", "TimeoutExpired"),
        ("w32tm_failed", "CalledProcessError"),
        ("w32tm_hung", "TimeoutExpired"),
        ("resource_denied", "AccessDenied"),
        ("resource_gone", "NoSuchProcess"),
    ],
)
def test_cli_process_and_resource_failures_are_redacted_blocked_never_a_traceback(
    case, error_class, tmp_path, monkeypatch, capsys
):
    module, _, _, _, _, _ = cli_authorized_fixture(tmp_path, monkeypatch)
    sensitive = "SYNTHETIC_SENSITIVE_" + "x" * 40
    tool, kind = case.split("_")
    command = [str(tmp_path / tool), sensitive]
    if kind == "failed":
        error = subprocess.CalledProcessError(128, command, output=sensitive, stderr=sensitive)
    elif kind == "hung":
        error = subprocess.TimeoutExpired(command, 3, output=sensitive, stderr=sensitive)
    elif kind == "denied":
        error = psutil.AccessDenied(pid=4, name=sensitive)
    else:
        error = psutil.NoSuchProcess(pid=4, name=sensitive)
    assert isinstance(error, (subprocess.SubprocessError, psutil.Error))
    assert type(error).__name__ == error_class and sensitive in (str(error) + repr(error))

    def fail(*_args, **_kwargs):
        raise error

    if tool in ("git", "w32tm"):
        # The real gates run; only the process they would start raises the real class.
        monkeypatch.setattr(oi_runtime, "git_executable", lambda _root: tmp_path / "git")
        monkeypatch.setattr(oi_runtime, "w32tm_executable", lambda: tmp_path / "w32tm.exe")
        monkeypatch.setattr(oi_runtime.subprocess, "check_output", fail)
        monkeypatch.setattr(oi_runtime.subprocess, "run", fail)
        if tool == "git":
            monkeypatch.setattr(module, "require_build", oi_runtime.require_build)
        else:
            monkeypatch.setattr(module, "inspect_clock", oi_runtime.inspect_clock)
        monkeypatch.setattr(
            module, "load_oi_database_password", lambda: pytest.fail("secret after failed gate")
        )
        monkeypatch.setattr(
            module, "create_engine", lambda *_a, **_kw: pytest.fail("DB after failed gate")
        )
    else:
        # The real resource probe wrapper runs against a measurement that raises.
        probe = SimpleNamespace(virtual_memory=fail, cpu_percent=fail, disk_usage=fail)
        monkeypatch.setattr(oi_runtime.importlib, "import_module", lambda _name: probe)
        cli_fake_runtime(module, monkeypatch, lambda job: job.resources_ready())
    status = module.main()
    output = capsys.readouterr()
    _check_sensitive(not output.err and "SYNTHETIC_SENSITIVE" not in output.out)
    assert status == 2
    assert json.loads(output.out) == {
        "status": "BLOCKED",
        "reason": "OI_PREFLIGHT_OR_PERSISTENCE_FAILED",
        "error_class": error_class,
        "forward_days": 0,
    }


def test_cli_reports_recorded_research_failures_with_nonzero_exit(tmp_path, monkeypatch, capsys):
    module, _, _, _, _, _ = cli_authorized_fixture(tmp_path, monkeypatch)
    failures = ("BTCUSDT:OI_LEDGER_FEATURE_BINDING",)
    cli_fake_runtime(
        module,
        monkeypatch,
        lambda _job: OIJobStatus(
            "LEDGER_REVIEW_REQUIRED",
            "OI_RESEARCH_LEDGER_FAILED",
            ("a" * 64, "b" * 64),
            research_failures=failures,
        ),
    )
    assert module.main() == 6
    assert json.loads(capsys.readouterr().out) == {
        "status": "LEDGER_REVIEW_REQUIRED",
        "reason": "OI_RESEARCH_LEDGER_FAILED",
        "manifest_hashes": ["a" * 64, "b" * 64],
        "research_failures": list(failures),
        "forward_days": 0,
    }

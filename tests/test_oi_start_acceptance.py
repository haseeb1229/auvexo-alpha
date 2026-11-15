"""OI-4/OI-9 proofs: committed START acceptance, build ancestry and the clock diagnostic.

No Git object, ref or real START is created: Git is replaced by recorded fakes. No
Windows Time state is read or changed: the clock inputs are fixed text.
"""

import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from auvexo_alpha.domain.oi_schedule import (
    OI_START_ACCEPTANCE_PATH,
    OICollectionConfig,
    OIRuntimeIdentity,
    OIStartAcceptance,
    OIStartAcceptanceFile,
    OIStartEnvelope,
)
from auvexo_alpha.infrastructure import oi_runtime

NOW = datetime(2026, 10, 30, 12, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]
RELEASE = "a" * 40
ACCEPTANCE_COMMIT = "b" * 40
RUNTIME = OIRuntimeIdentity(
    checkout_root="C:/synthetic/oi-runtime",
    python_executable="C:/synthetic/oi-runtime/python.exe",
    python_executable_sha256="1" * 64,
    base_interpreter_sha256="2" * 64,
)


def configuration(**changes):
    values = dict(
        enabled=True,
        git_revision=RELEASE,
        code_hash="b" * 64,
        lock_hash="c" * 64,
        preregistration_hash="d" * 64,
        study_id="synthetic-oi",
        clock_source="synthetic-ntp",
    )
    values.update(changes)
    return OICollectionConfig(**values)


def acceptance_entry(config, owner="synthetic-owner-ref"):
    envelope = OIStartEnvelope(
        owner_authorization_ref=owner,
        independent_review_ref="synthetic-review-ref",
        implementation_revision=config.git_revision,
        config_hash=config.content_hash(),
        code_hash=config.code_hash,
        source_hash=config.source.content_hash(),
        rights_hash=config.rights.content_hash(),
        preregistration_hash=config.preregistration_hash,
        issued_at=NOW - timedelta(days=3, minutes=2),
        owner_start_at=NOW - timedelta(days=3, minutes=1),
        expires_at=NOW + timedelta(days=1),
    )
    return OIStartAcceptance(
        study_id=config.study_id,
        envelope=envelope,
        runtime=RUNTIME,
        commissioning_clock_source=config.clock_source,
        commissioning_clock_evidence_hash="9" * 64,
        acceptance_review_ref="synthetic-independent-review",
    )


class FakeGit:
    """Answers only the read-only plumbing the gates use; records every command."""

    def __init__(self, monkeypatch, *, head=RELEASE, status="", base=RELEASE, diff="", blob=b""):
        self.head, self.status, self.base, self.diff, self.blob = head, status, base, diff, blob
        self.size = None
        self.commands = []
        monkeypatch.setattr(oi_runtime, "git_executable", lambda _root: Path("/synthetic/git"))
        monkeypatch.setattr(oi_runtime.subprocess, "check_output", self.run)

    def run(self, args, **kwargs):
        self.commands.append(list(args))
        verb = args[4]
        if verb == "rev-parse":
            return self.head + "\n"
        if verb == "status":
            return self.status
        if verb == "merge-base":
            return self.base + "\n"
        if verb == "diff":
            return self.diff
        if verb == "cat-file" and args[5] == "-s":
            return f"{len(self.blob) if self.size is None else self.size}\n"
        if verb == "cat-file" and args[5] == "blob":
            assert "text" not in kwargs
            return self.blob
        raise AssertionError(args)


def build_tree(tmp_path, monkeypatch):
    (tmp_path / "src/auvexo_alpha").mkdir(parents=True)
    (tmp_path / "tools").mkdir()
    (tmp_path / "docs/phase6").mkdir(parents=True)
    for path in (
        "src/auvexo_alpha/a.py",
        "tools/oi_task.py",
        "tools/run_oi_collection.py",
        "uv.lock",
        "docs/phase6/EXPERIMENT_PREREGISTRATION.md",
    ):
        (tmp_path / path).write_text("synthetic fixture", encoding="utf8")
    monkeypatch.setattr(
        oi_runtime, "loaded_package_directory", lambda: tmp_path / "src/auvexo_alpha"
    )

    def digest(path):
        return hashlib.sha256((tmp_path / path).read_bytes()).hexdigest()

    return configuration(
        code_hash=oi_runtime.oi_code_hash(tmp_path),
        lock_hash=digest("uv.lock"),
        preregistration_hash=digest("docs/phase6/EXPERIMENT_PREREGISTRATION.md"),
    )


def test_build_at_the_release_itself_needs_no_ancestry_query(tmp_path, monkeypatch):
    config = build_tree(tmp_path, monkeypatch)
    git = FakeGit(monkeypatch)
    assert oi_runtime.require_build(tmp_path, config) == RELEASE
    assert [command[4] for command in git.commands] == ["rev-parse", "status"]


def test_head_may_add_only_the_committed_acceptance_file_on_top_of_the_release(
    tmp_path, monkeypatch
):
    config = build_tree(tmp_path, monkeypatch)
    git = FakeGit(monkeypatch, head=ACCEPTANCE_COMMIT, diff=OI_START_ACCEPTANCE_PATH + "\0")
    assert oi_runtime.require_build(tmp_path, config) == ACCEPTANCE_COMMIT
    merge_base, diff = git.commands[2], git.commands[3]
    assert merge_base[4:] == ["merge-base", RELEASE, ACCEPTANCE_COMMIT]
    assert diff[4:] == ["diff", "--name-only", "--no-renames", "-z", RELEASE, ACCEPTANCE_COMMIT]


@pytest.mark.parametrize(
    "change",
    [
        {"base": "c" * 40},  # the release is not an ancestor of HEAD
        {"diff": ""},  # a different commit with no acceptance file
        {"diff": OI_START_ACCEPTANCE_PATH + "\0src/auvexo_alpha/a.py\0"},
        {"diff": "src/auvexo_alpha/a.py\0"},
        {"diff": "acceptance/other.json\0"},
        {"diff": OI_START_ACCEPTANCE_PATH.upper() + "\0"},
        {"status": " M " + OI_START_ACCEPTANCE_PATH + "\0"},  # uncommitted local edit
        {"head": "not-a-commit"},
    ],
)
def test_any_other_difference_from_the_release_refuses(change, tmp_path, monkeypatch):
    config = build_tree(tmp_path, monkeypatch)
    values = {"head": ACCEPTANCE_COMMIT, "diff": OI_START_ACCEPTANCE_PATH + "\0"} | change
    FakeGit(monkeypatch, **values)
    with pytest.raises(ValueError, match="OI_BUILD_BINDING"):
        oi_runtime.require_build(tmp_path, config)


def test_acceptance_is_read_from_the_proven_commit_tree_never_the_working_tree(
    tmp_path, monkeypatch
):
    config = configuration()
    entry = acceptance_entry(config)
    committed = OIStartAcceptanceFile(accepted=(entry,))
    git = FakeGit(monkeypatch, blob=committed.canonical_bytes())
    # A working-tree file at the same path is never consulted.
    planted = tmp_path / OI_START_ACCEPTANCE_PATH
    planted.parent.mkdir(parents=True)
    planted.write_bytes(
        OIStartAcceptanceFile(accepted=(acceptance_entry(config, "self-issued"),)).canonical_bytes()
    )
    start = oi_runtime.load_accepted_start(tmp_path, ACCEPTANCE_COMMIT, entry.content_hash())
    assert start.acceptance == entry and start.acceptance_commit == ACCEPTANCE_COMMIT
    assert start.digest == entry.content_hash()
    blob = f"{ACCEPTANCE_COMMIT}:{OI_START_ACCEPTANCE_PATH}"
    assert [command[4:] for command in git.commands] == [
        ["cat-file", "-s", blob],
        ["cat-file", "blob", blob],
    ]
    for digest in (acceptance_entry(config, "self-issued").content_hash(), "0" * 64):
        with pytest.raises(ValueError, match="OI_START_NOT_ACCEPTED"):
            oi_runtime.load_accepted_start(tmp_path, ACCEPTANCE_COMMIT, digest)


def duplicate_key_blob(config):
    text = OIStartAcceptanceFile(accepted=(acceptance_entry(config),)).canonical_bytes().decode()
    return text.replace('{"accepted":', '{"version":"oi-start-acceptance-file.v1","accepted":', 1)


@pytest.mark.parametrize(
    "case",
    [
        "duplicate_key",
        "size_mismatch",
        "oversize",
        "empty",
        "not_json",
        "deep",
        "wrong_schema",
        "bad_commit",
    ],
)
def test_committed_file_must_be_bounded_strict_and_exact(case, tmp_path, monkeypatch):
    config = configuration()
    blob = OIStartAcceptanceFile(accepted=(acceptance_entry(config),)).canonical_bytes()
    git = FakeGit(monkeypatch, blob=blob)
    commit = ACCEPTANCE_COMMIT
    if case == "duplicate_key":
        git.blob = duplicate_key_blob(config).encode()
        assert json.loads(git.blob)["version"] == "oi-start-acceptance-file.v1"
    elif case == "size_mismatch":
        git.size = len(blob) + 1
    elif case == "oversize":
        git.size = 65537
    elif case == "empty":
        git.blob = b""
    elif case == "not_json":
        git.blob = b"\xff\xfe"
    elif case == "deep":
        # Refused on every platform, whichever parser reaches the nesting limit first.
        git.blob = b"[" * 5000 + b"]" * 5000
    elif case == "wrong_schema":
        # Well-formed JSON that only the strict model refuses still gets the closed code.
        git.blob = b'{"version":"oi-start-acceptance-file.v1","accepted":"none"}'
    else:
        commit = "HEAD"
    with pytest.raises(ValueError, match="OI_START_ACCEPTANCE_INVALID"):
        oi_runtime.committed_start_acceptances(tmp_path, commit)
    if case in ("oversize", "bad_commit"):
        assert all(command[5] != "blob" for command in git.commands)


def test_runtime_identity_is_this_checkout_and_interpreter_bytes():
    identity = oi_runtime.runtime_identity(ROOT)
    assert identity.checkout_root == str(ROOT.resolve())
    executable = Path(sys.executable).resolve()
    assert identity.python_executable == str(executable)
    assert identity.python_executable_sha256 == hashlib.sha256(executable.read_bytes()).hexdigest()
    acceptance_entry(configuration()).model_copy(update={"runtime": identity}).require_runtime(
        identity
    )


# Measured on this development host on 2026-11-13 (read-only w32tm query); source kept.
UNSYNCHRONIZED_HOST = (
    "Leap Indicator: 3(not synchronized)\nStratum: 0 (unspecified)\n"
    "Precision: -23 (119.209ns per tick)\nRoot Delay: 0.2124412s\n"
    "Root Dispersion: 38.6061305s\nReferenceId: 0x00000000 (unspecified)\n"
    "Last Successful Sync Time: 11/13/2026 1:18:59 AM\nSource: time.windows.com,0x9 \n"
    "Poll Interval: 10 (1024s)\n\nPhase Offset: 30.8359811s\n"
    "Last Sync Error: 1 (The computer did not resync because no time data was available.)\n"
    "Time since Last Good Sync Time: 3817.4532708s\n"
)
SYNCHRONIZED_HOST = (
    "Leap Indicator: 0(no warning)\nStratum: 4 (secondary reference - syncd by (S)NTP)\n"
    "Root Delay: 0.0312500s\nRoot Dispersion: 0.0421875s\n"
    "Source: time.windows.com,0x9 \nPhase Offset: -0.0012345s\n"
    "Time since Last Good Sync Time: 812.25s\n"
)


def status_of(diagnosis):
    return {check.name: check.status for check in diagnosis.checks}


def test_diagnosis_names_every_failing_input_of_the_unsynchronized_host():
    diagnosis = oi_runtime.diagnose_clock_status(UNSYNCHRONIZED_HOST, "time.windows.com,0x9")
    assert not diagnosis.trusted
    assert diagnosis.failing == (
        "leap_indicator",
        "stratum",
        "time_since_last_good_sync",
        "offset_bound",
    )
    assert (
        diagnosis.bound
        == abs(Decimal("30.8359811")) + Decimal("38.6061305") + Decimal("0.2124412") / 2
    )


def test_diagnosis_passes_a_synchronized_host_polling_inside_the_sync_age_limit():
    diagnosis = oi_runtime.diagnose_clock_status(SYNCHRONIZED_HOST, "time.windows.com,0x9")
    assert diagnosis.trusted and diagnosis.failing == ()
    assert set(status_of(diagnosis).values()) == {"PASS"}


@pytest.mark.parametrize(
    "variant,failing",
    [
        (("812.25s", "3600.000000001s"), "time_since_last_good_sync"),
        (("812.25s", "-1s"), "time_since_last_good_sync"),
        (("-0.0012345s", "0.95s"), "offset_bound"),
        (("Leap Indicator: 0", "Leap Indicator: 1"), "leap_indicator"),
        (("Stratum: 4", "Stratum: 16"), "stratum"),
        (("Source: time.windows.com,0x9", "Source: Local CMOS Clock"), "source_not_local"),
        (("Root Delay: 0.0312500s", "Root Delay: -0.03s"), "root_delay"),
        (("Phase Offset: -0.0012345s", "Phase Offset: 1e-3s"), "phase_offset"),
        (("Source:", "Quelle:"), "source_not_local"),
    ],
)
def test_each_input_fails_alone_and_the_gate_refuses_exactly_then(variant, failing, monkeypatch):
    output = SYNCHRONIZED_HOST.replace(*variant)
    diagnosis = oi_runtime.diagnose_clock_status(output, "time.windows.com,0x9")
    assert failing in diagnosis.failing and not diagnosis.trusted
    monkeypatch.setattr(oi_runtime, "read_clock_status", lambda: output)
    with pytest.raises(ValueError, match="OI_CLOCK_UNTRUSTED"):
        oi_runtime.inspect_clock("time.windows.com,0x9")


def test_sync_age_limit_is_inclusive_at_exactly_one_hour(monkeypatch):
    output = SYNCHRONIZED_HOST.replace("812.25s", "3600s")
    monkeypatch.setattr(oi_runtime, "read_clock_status", lambda: output)
    proof = oi_runtime.inspect_clock("time.windows.com,0x9")
    assert proof.time_since_sync_seconds == 3600 and proof.offset_bound_ms == 60


def test_unconfigured_source_is_reported_not_checked_and_never_trusted():
    diagnosis = oi_runtime.diagnose_clock_status(SYNCHRONIZED_HOST, None)
    assert status_of(diagnosis)["source_equals_configured"] == "NOT_CHECKED"
    assert diagnosis.failing == () and not diagnosis.trusted
    mismatch = oi_runtime.diagnose_clock_status(SYNCHRONIZED_HOST, "time.windows.com")
    assert mismatch.failing == ("source_equals_configured",)


def clock_tool():
    spec = importlib.util.spec_from_file_location(
        "oi_clock_status", ROOT / "tools/oi_clock_status.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("output,code", [(SYNCHRONIZED_HOST, 0), (UNSYNCHRONIZED_HOST, 2)])
def test_clock_status_tool_reports_each_input_read_only(output, code, monkeypatch, capsys):
    module = clock_tool()
    monkeypatch.setattr(module, "read_clock_status", lambda: output)
    monkeypatch.setattr(module, "time_service_settings", lambda: {"available": False})
    monkeypatch.setattr(module.sys, "argv", ["oi_clock_status", "--source", "time.windows.com,0x9"])
    assert module.main() == code
    report = json.loads(capsys.readouterr().out)
    assert report["trusted"] is (code == 0)
    assert [row["input"] for row in report["checks"]][-1] == "source_equals_configured"
    if code:
        assert report["failing"] == [
            "leap_indicator",
            "stratum",
            "time_since_last_good_sync",
            "offset_bound",
        ]


def test_clock_status_tool_reports_a_failed_query_by_class_only(monkeypatch, capsys):
    module = clock_tool()

    def fail():
        raise module.subprocess.CalledProcessError(5, ["w32tm", "SYNTHETIC_SENSITIVE"])

    monkeypatch.setattr(module, "read_clock_status", fail)
    monkeypatch.setattr(module.sys, "argv", ["oi_clock_status"])
    assert module.main() == 2
    output = capsys.readouterr().out
    assert json.loads(output) == {"trusted": False, "query_error": "CalledProcessError"}
    assert "SYNTHETIC_SENSITIVE" not in output


def test_clock_tool_source_has_no_mutating_time_command():
    source = (ROOT / "tools/oi_clock_status.py").read_text(encoding="utf8")
    for forbidden in ("/resync", "/config", "/register", "SetValue", "CreateKey", "net start"):
        assert forbidden not in source

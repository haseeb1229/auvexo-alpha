"""Future local PAPER observation entrypoint; no START or task registration capability."""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event

import psutil
from sqlalchemy.exc import SQLAlchemyError

if __package__:
    from tools.paper_observation_local import ROOT, engine_for
else:
    from paper_observation_local import ROOT, engine_for

from auvexo_alpha.application.observation_runner import ObservationRunner
from auvexo_alpha.domain.observation import (
    ObservationConfig,
    ObservationResources,
    observation_window,
)
from auvexo_alpha.infrastructure.data_store import DataStore
from auvexo_alpha.infrastructure.observation_feed import ObservationFeed
from auvexo_alpha.infrastructure.observation_paper import (
    ObservationPaperCommands,
    ObservationPaperTruth,
)
from auvexo_alpha.infrastructure.observation_simulator import CausalPaperSimulator
from auvexo_alpha.infrastructure.observation_store import ObservationStore
from auvexo_alpha.infrastructure.paper_identity import PaperIdentityError
from auvexo_alpha.infrastructure.paper_store import PaperStore
from auvexo_alpha.infrastructure.paper_truth import PaperTruth
from auvexo_alpha.infrastructure.public_http import PublicHTTP


class ResourceSampler:
    """CPU duration is monotonic; wall-clock changes cannot invent sustained pressure."""

    def __init__(self) -> None:
        self.high_since: float | None = None

    def __call__(self, now: datetime) -> ObservationResources:
        cpu = psutil.cpu_percent()
        tick = time.monotonic()
        if cpu > 80:
            self.high_since = self.high_since if self.high_since is not None else tick
        else:
            self.high_since = None
        return ObservationResources(
            observed_at=now,
            available_ram_bytes=psutil.virtual_memory().available,
            cpu_percent=Decimal(str(cpu)),
            cpu_high_for_seconds=max(0, int(tick - self.high_since))
            if self.high_since is not None
            else 0,
        )


def verify_scheduled_source(config: ObservationConfig) -> None:
    """The activated SHA must be the running committed, executable-clean checkout."""
    git = ["git", "-c", "safe.directory=" + ROOT.as_posix(), "-C", str(ROOT)]
    head = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
    paths = [
        "src",
        "tests",
        "tools",
        "migrations",
        "alembic.ini",
        "alembic-observation.ini",
        "pyproject.toml",
        "uv.lock",
        ".github",
        "AGENTS.md",
        "CLAUDE.md",
    ]
    changed = subprocess.check_output([*git, "diff", "--name-only", "HEAD", "--", *paths])
    untracked = subprocess.check_output(
        [*git, "ls-files", "--others", "--exclude-standard", "--", *paths]
    )
    if head != config.git_revision or changed.strip() or untracked.strip():
        raise ValueError("OBSERVATION_REVIEWED_SOURCE_MISMATCH")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Local envelope with database and campaign fields",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--scheduled", action="store_true")
    mode.add_argument(
        "--preflight", action="store_true", help="NON_COUNTING, never genuine day credit"
    )
    args = parser.parse_args()
    payload = json.loads(args.config.read_text())
    if not isinstance(payload, dict) or set(payload) != {"database", "campaign"}:
        raise ValueError("OBSERVATION_LAUNCH_CONFIG_INVALID")
    config = ObservationConfig.model_validate_json(json.dumps(payload["campaign"]))
    if args.scheduled:
        verify_scheduled_source(config)
    runtime = engine_for(payload["database"], "auvexo_paper")
    truth_engine = engine_for(payload["database"], "auvexo_paper_truth")
    owner = engine_for(payload["database"], "auvexo_paper_owner") if args.prepare else None
    cancel = Event()
    signal.signal(signal.SIGINT, lambda signum, frame: cancel.set())
    signal.signal(signal.SIGTERM, lambda signum, frame: cancel.set())
    try:
        source = DataStore(
            truth_engine, ROOT / ".local/observation" / payload["database"] / "market", ROOT
        )
        store = ObservationStore(runtime, owner, truth_engine, source_store=source)
        now = datetime.now(UTC)
        if args.prepare:
            store.prepare(config, now=now)
            print(
                json.dumps({"state": "PREPARED", "observation_days": 0, "task_registered": False})
            )
            return 0
        if not args.scheduled and not args.preflight:
            print(
                json.dumps(
                    {
                        "state": "ACTIVE"
                        if store.activation(config.content_hash())
                        else "PREPARED",
                        "observation_days": store.qualified_dates(
                            config.content_hash(), now=now
                        ).qualified_count,
                        "task_registered_by_this_tool": False,
                    }
                )
            )
            return 0
        _, end = observation_window(now.date())
        cutoff = end - timedelta(seconds=30)

        def bounded_wait(seconds: float) -> bool:
            if datetime.now(UTC) >= cutoff:
                return True
            return cancel.wait(seconds) or datetime.now(UTC) >= cutoff

        http = PublicHTTP(cancel, wait=bounded_wait, max_requests=256)
        feed = ObservationFeed(source, http, config.git_revision, config.campaign_id)
        paper = PaperStore(runtime)
        truth = PaperTruth(truth_engine)
        runner = ObservationRunner(
            config,
            store,
            ObservationPaperCommands(paper),
            ObservationPaperTruth(truth),
            feed,
            simulator=CausalPaperSimulator(paper, truth),
            cancel=cancel,
            resources=ResourceSampler(),
            # This process never starts an optional research worker. No arbitrary OS
            # processes are stopped or silently claimed to have been throttled.
            pause_optional_research=lambda: True,
        )
        receipt = runner.run(kind="SCHEDULED" if args.scheduled else "PREFLIGHT")
        print(receipt.model_dump_json())
        return 0 if receipt.status == "PASS" else 2
    finally:
        runtime.dispose()
        truth_engine.dispose()
        if owner is not None:
            owner.dispose()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, SQLAlchemyError, PaperIdentityError) as error:
        # Exception text can contain local paths or SQL/credential context.
        print(
            json.dumps(
                {
                    "code": "OBSERVATION_REFUSED",
                    "error_type": type(error).__name__,
                    "execution_enabled": False,
                }
            )
        )
        raise SystemExit(2) from None

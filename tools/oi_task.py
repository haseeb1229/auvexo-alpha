"""Render disabled future OI task XML only; no Task Scheduler mutation or START issuer."""

import argparse
import re
from datetime import datetime
from pathlib import Path
from subprocess import list2cmdline
from xml.etree.ElementTree import Element, SubElement, tostring

from auvexo_alpha.domain.contracts import utc_time


def task_definition(
    *,
    owner: str,
    python: Path,
    script: Path,
    config: Path,
    start: datetime,
    start_envelope: Path | None = None,
    accepted_start_hash: str | None = None,
    review_chain: Path | None = None,
    accepted_review_hashes: tuple[str, ...] = (),
) -> str:
    start = utc_time(start)
    if (
        start != start.replace(minute=0, second=0, microsecond=0)
        or not owner.strip()
        or owner.casefold().replace(" ", "")
        in {
            "system",
            "ntauthority\\system",
            "localservice",
            "networkservice",
            "ntauthority\\localservice",
            "ntauthority\\networkservice",
            "s-1-5-18",
            "s-1-5-19",
            "s-1-5-20",
        }
        or not all(p.is_absolute() for p in (python, script, config))
        or any("\x00" in str(p) for p in (owner, python, script, config))
    ):
        raise ValueError("OI_TASK_CONFIG")
    if (
        (start_envelope is None) != (accepted_start_hash is None)
        or (
            start_envelope is not None
            and (not start_envelope.is_absolute() or "\x00" in str(start_envelope))
        )
        or (
            accepted_start_hash is not None
            and not re.fullmatch(r"[0-9a-f]{64}", accepted_start_hash)
        )
    ):
        raise ValueError("OI_TASK_CONFIG")
    if (
        (review_chain is None) != (not accepted_review_hashes)
        or (
            review_chain is not None
            and (not review_chain.is_absolute() or "\x00" in str(review_chain))
        )
        or len(accepted_review_hashes) > 32
        or len(set(accepted_review_hashes)) != len(accepted_review_hashes)
        or any(not re.fullmatch(r"[0-9a-f]{64}", h) for h in accepted_review_hashes)
    ):
        raise ValueError("OI_TASK_REVIEW_CHAIN_CONFIG")
    root = Element(
        "Task", {"version": "1.4", "xmlns": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    )
    info = SubElement(root, "RegistrationInfo")
    SubElement(info, "Description").text = "DS04-A1 ENGINEERING_ONLY disabled definition; no START"
    trigger = SubElement(SubElement(root, "Triggers"), "TimeTrigger")
    repetition = SubElement(trigger, "Repetition")
    SubElement(repetition, "Interval").text = "PT1H"
    SubElement(repetition, "StopAtDurationEnd").text = "false"
    SubElement(trigger, "StartBoundary").text = start.isoformat().replace("+00:00", "Z")
    SubElement(trigger, "Enabled").text = "false"
    principal = SubElement(SubElement(root, "Principals"), "Principal", {"id": "Owner"})
    for name, value in (
        ("UserId", owner),
        ("LogonType", "InteractiveToken"),
        ("RunLevel", "LeastPrivilege"),
    ):
        SubElement(principal, name).text = value
    settings = SubElement(root, "Settings")
    for name, value in (
        ("MultipleInstancesPolicy", "IgnoreNew"),
        ("StartWhenAvailable", "false"),
        ("AllowStartOnDemand", "false"),
        ("Enabled", "false"),
        ("WakeToRun", "false"),
        ("RunOnlyIfNetworkAvailable", "true"),
        ("ExecutionTimeLimit", "PT1M"),
        ("Priority", "7"),
    ):
        SubElement(settings, name).text = value
    action = SubElement(SubElement(root, "Actions", {"Context": "Owner"}), "Exec")
    SubElement(action, "Command").text = str(python)
    arguments = [
        "-B",
        str(script),
        "--config",
        str(config),
        "--scheduled",
    ]
    if start_envelope is not None and accepted_start_hash is not None:
        arguments.extend(
            ["--start-envelope", str(start_envelope), "--accepted-start-hash", accepted_start_hash]
        )
    if review_chain is not None:
        arguments.extend(["--review-chain", str(review_chain)])
        for digest in accepted_review_hashes:
            arguments.extend(["--accepted-review-hash", digest])
    SubElement(action, "Arguments").text = list2cmdline(arguments)
    SubElement(action, "WorkingDirectory").text = str(script.parent.parent)
    return '<?xml version="1.0" encoding="UTF-16"?>\n' + tostring(root, encoding="unicode")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--start", type=datetime.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-envelope", type=Path)
    parser.add_argument("--accepted-start-hash")
    parser.add_argument("--review-chain", type=Path)
    parser.add_argument("--accepted-review-hash", action="append", default=[])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if not output.is_relative_to(root / ".local/phase6"):
        parser.error("output must be ignored Development-local Phase6 preparation")
    xml = task_definition(
        owner=args.owner,
        python=args.python,
        script=args.script,
        config=args.config,
        start=args.start,
        start_envelope=args.start_envelope,
        accepted_start_hash=args.accepted_start_hash,
        review_chain=args.review_chain,
        accepted_review_hashes=tuple(args.accepted_review_hash),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-16") as handle:
        handle.write(xml)
    print("OI_TASK_DEFINITION_ONLY_DISABLED_NO_START")


if __name__ == "__main__":
    main()

"""Explicitly started, local deterministic research executor. No external providers."""

import argparse
import hashlib
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import Engine

from alphasense.db import (
    ReportStore,
    RevisionConflict,
    StoreUnavailable,
    UnstorableReport,
    get_store,
)
from alphasense.instruments import InstrumentStore
from alphasense.run_contracts import RunAdvance, RunFinish
from alphasense.runs import ResearchStore, RunConflict
from alphasense.snapshots import SnapshotStore
from alphasense.worker_engine import (
    WorkerInputError,
    compile_report,
    fundamental_section,
    load_input,
    technical_section,
)
from alphasense.worker_store import WorkerLeaseLost, WorkerStore

ROOT = Path(__file__).resolve().parents[4]


def implementation_fingerprint() -> str:
    digest = hashlib.sha256()
    files = sorted(Path(__file__).parent.glob("*.py")) + [ROOT / "requirements-dev.lock"]
    for path in files:
        digest.update(path.name.encode("utf-8") + b"\0")
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big") + content)
    return digest.hexdigest()


def current_git_sha() -> str:
    revision = os.environ.get("ALPHASENSE_BUILD_GIT_SHA")
    if revision is not None:
        if not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", revision):
            raise ValueError("Invalid build revision")
        return revision
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.strip()


def process_once(
    engine: Engine,
    worker_id: str,
    git_sha: str,
    implementation_hash: str,
    lease_seconds: int = 60,
    *,
    run_id: UUID | None = None,
) -> bool:
    jobs = WorkerStore(engine)
    lease = jobs.claim(worker_id, implementation_hash, git_sha, lease_seconds, run_id=run_id)
    if lease is None:
        return False
    runs = ResearchStore(engine)
    try:
        state = runs.get(lease.run_id)
        instrument = InstrumentStore(engine).get(state.instrument_id)
        archive = SnapshotStore(engine)
        snapshots = [archive.content(snapshot_id) for snapshot_id in state.snapshot_ids]
        while True:
            lease = jobs.renew(lease)
            state = runs.get(lease.run_id)
            step = state.current_step
            if step is None:
                return True
            if step == "review":
                expected = compile_report(
                    state, instrument, snapshots, git_sha, implementation_hash
                )
                stored = ReportStore(engine).get_report(expected.report_id)
                if stored.model_dump(mode="json") != expected.model_dump(mode="json"):
                    raise WorkerInputError("REPORT_REVIEW_MISMATCH")
                jobs.finish(
                    lease,
                    RunFinish(
                        action="finish",
                        report_revision_id=expected.revision_id,
                        request_id=uuid4(),
                        expected_sequence=state.sequence,
                        actor=worker_id,
                    ),
                )
                return True
            command = RunAdvance(
                action="advance",
                step=step,
                request_id=uuid4(),
                expected_sequence=state.sequence,
                actor=worker_id,
            )
            if step == "report":
                result = compile_report(state, instrument, snapshots, git_sha, implementation_hash)
                jobs.publish(lease, result, command)
                continue
            if step != "data":
                data = load_input(state, instrument, snapshots)
                if step == "fundamental":
                    fundamental_section(data)
                elif step == "technical":
                    technical_section(data)
            jobs.apply(lease, command)
    except WorkerInputError as error:
        jobs.fail(lease, error.code, "Deterministic input or report validation failed")
    except (ValidationError, RevisionConflict, UnstorableReport) as error:
        code = "INPUT_INVALID"
        if isinstance(error, RevisionConflict):
            code = "REPORT_CONFLICT"
        elif isinstance(error, UnstorableReport):
            code = "INPUT_UNSTORABLE"
        jobs.fail(lease, code, "Deterministic input or report validation failed")
    except WorkerLeaseLost:
        # Another worker may own the run; do not write anything under stale ownership.
        pass
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Process at most one run (default)")
    mode.add_argument("--forever", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2)
    parser.add_argument("--worker-id", default="local-worker")
    parser.add_argument("--lease-seconds", type=int, default=60)
    parser.add_argument("--git-sha")
    parser.add_argument(
        "--run-id", type=UUID, help="Process only this run; leave other jobs untouched"
    )
    args = parser.parse_args(argv)
    if not 0.1 <= args.poll_seconds <= 60 or not 15 <= args.lease_seconds <= 300:
        parser.error("Poll must be 0.1–60 seconds and lease 15–300 seconds")
    try:
        store = get_store()
        store.check_ready()
        git_sha = args.git_sha or current_git_sha()
        fingerprint = implementation_fingerprint()
        while True:
            processed = process_once(
                store.engine,
                args.worker_id,
                git_sha,
                fingerprint,
                args.lease_seconds,
                run_id=args.run_id,
            )
            if not args.forever:
                print(
                    "Worker processed one run"
                    if processed
                    else "Worker did not claim a runnable job"
                )
                return 0
            if not processed:
                time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        return 0
    except (
        StoreUnavailable,
        RunConflict,
        ValidationError,
        ValueError,
        OSError,
        subprocess.SubprocessError,
    ):
        print(
            "Worker stopped: configuration, storage or ownership unavailable; "
            "unfinished leases remain recoverable",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

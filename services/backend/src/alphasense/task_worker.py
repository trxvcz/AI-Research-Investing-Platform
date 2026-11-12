"""Separate durable import executor. No provider errors are automatically retried."""

import argparse
import subprocess
from threading import Event, Thread
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from alphasense.db import ReportStore, StoreUnavailable, get_store
from alphasense.panel_launch import analysis_state, fetch_sec
from alphasense.provider_policy import ProviderDenied, load_policy
from alphasense.runs import ResearchStore, RunConflict
from alphasense.sec_fundamentals import SecInputError
from alphasense.sec_import import SecImporter
from alphasense.sec_transport import SecResponse, SecTransportError
from alphasense.tasks import TaskLeaseLost, TaskStore
from alphasense.worker import current_git_sha, implementation_fingerprint, process_once
from alphasense.worker_session_runtime import WorkerSessionMonitor


def process_task_once(engine: Engine, worker_id: str) -> bool:
    tasks = TaskStore(engine)
    claim = tasks.claim(worker_id)
    if claim is None:
        return False
    token, frozen = claim
    stop, lost = Event(), Event()

    def heartbeat() -> None:
        while not stop.wait(5):
            try:
                tasks.heartbeat(frozen.run_id, token)
            except (TaskLeaseLost, StoreUnavailable, SQLAlchemyError):
                lost.set()
                return

    def guarded_fetch(payload: object) -> SecResponse:
        if lost.is_set():
            raise TaskLeaseLost()
        tasks.heartbeat(frozen.run_id, token)
        return fetch_sec(payload)

    thread = Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        state = SecImporter(engine, load_policy(), guarded_fetch).import_run(frozen)
        if lost.is_set():
            raise TaskLeaseLost()
        tasks.change(frozen.run_id, token, stage="analysis", instrument_id=frozen.instrument_id)
        if state.status in {"queued", "running"}:
            process_once(
                engine,
                worker_id,
                current_git_sha(),
                implementation_fingerprint(),
                run_id=frozen.run_id,
            )
        state = ResearchStore(engine).get(frozen.run_id)
        if lost.is_set():
            raise TaskLeaseLost()
        if state.status == "completed":
            result = analysis_state(frozen.run_id, ReportStore(engine))
            if result.report_id is None or result.revision is None:
                raise ValueError("Completed run lacks a report")
            tasks.finish(
                frozen.run_id,
                token,
                instrument_id=frozen.instrument_id,
                report_id=result.report_id,
                revision=result.revision,
            )
        elif state.status == "failed":
            tasks.fail(
                frozen.run_id,
                token,
                "ANALYSIS_FAILED",
                "Obliczenia zakończyły się błędem. Sprawdź przebieg analizy.",
            )
        # Another analysis worker may still own the research lease. Leave the
        # task recoverable after expiry, never claim that the report is ready.
    except ProviderDenied:
        tasks.fail(
            frozen.run_id,
            token,
            "SOURCE_POLICY_DENIED",
            "Polityka źródła lub limit zablokowały pobranie.",
        )
    except SecTransportError:
        tasks.fail(frozen.run_id, token, "SEC_UNAVAILABLE", "Nie udało się pobrać danych SEC.")
    except SecInputError:
        tasks.fail(
            frozen.run_id,
            token,
            "SEC_INPUT_UNSUPPORTED",
            "Dane SEC nie spełniają wymagań analizy.",
        )
    except TaskLeaseLost:
        pass
    except (RunConflict, ValidationError, ValueError, OSError, subprocess.SubprocessError):
        tasks.fail(
            frozen.run_id,
            token,
            "TASK_INPUT_INVALID",
            "Nie można wykonać zadania przy tej konfiguracji lub tożsamości.",
        )
    finally:
        stop.set()
        thread.join(timeout=10)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--forever", action="store_true")
    parser.add_argument("--worker-id", default="task-worker-" + uuid4().hex[:12])
    parser.add_argument("--poll-seconds", type=float, default=2)
    args = parser.parse_args(argv)
    if not 0.1 <= args.poll_seconds <= 60 or not 1 <= len(args.worker_id) <= 128:
        parser.error("Invalid worker configuration")
    try:
        store = get_store()
        store.check_ready()
        with WorkerSessionMonitor(
            store.engine, args.worker_id, "sec_import", "forever" if args.forever else "once"
        ) as monitor:
            while True:
                monitor.check()
                processed = process_task_once(store.engine, args.worker_id)
                monitor.check()
                if not args.forever:
                    print("Task processed" if processed else "No claimable task")
                    return 0
                if not processed:
                    monitor.wait(args.poll_seconds)
    except KeyboardInterrupt:
        return 0
    except (SQLAlchemyError, StoreUnavailable, TaskLeaseLost, OSError, ValueError):
        print("Task worker stopped; unfinished tasks remain recoverable")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

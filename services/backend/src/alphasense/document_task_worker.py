"""Separate deterministic document worker. This increment cannot invoke a model."""

import argparse
import hashlib
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from alphasense.db import StoreUnavailable, get_store
from alphasense.document_agent import validate_draft
from alphasense.document_archive import DocumentArchiveStore
from alphasense.document_tasks import DocumentTaskLeaseLost, DocumentTaskStore, input_hash
from alphasense.worker_session_runtime import WorkerSessionMonitor


def implementation_fingerprint() -> str:
    digest = hashlib.sha256()
    root = Path(__file__).parent
    for name in (
        "document_task_worker.py",
        "document_tasks.py",
        "document_task_contracts.py",
        "document_archive.py",
        "document_archive_contracts.py",
        "document_agent.py",
        "document_readers.py",
        "pdf_reader.py",
        "document_contracts.py",
    ):
        digest.update(name.encode("ascii") + b"\x00" + (root / name).read_bytes())
    return digest.hexdigest()


def process_document_once(engine: Engine, worker_id: str, *, lease_seconds: int = 120) -> bool:
    tasks = DocumentTaskStore(engine)
    claim = tasks.claim(worker_id, implementation_fingerprint(), lease_seconds)
    if claim is None:
        return False
    token, task = claim
    stop = Event()
    lost = Event()

    def heartbeat() -> None:
        while not stop.wait(lease_seconds / 3):
            try:
                tasks.renew(task.job_id, token, lease_seconds)
            except (DocumentTaskLeaseLost, SQLAlchemyError, StoreUnavailable):
                lost.set()
                return

    thread = Thread(target=heartbeat, name="document-heartbeat", daemon=True)
    thread.start()
    try:
        source = DocumentArchiveStore(engine).get(task.archive_id)
        if (
            source.document_sha256 != task.document_sha256
            or source.draft_sha256 != task.draft_sha256
            or input_hash(source) != task.input_sha256
        ):
            raise StoreUnavailable("Frozen document input unavailable")
        if lost.is_set():
            raise DocumentTaskLeaseLost("Document lease lost")
        tasks.stage(task.job_id, token, "validating")
        if task.mode == "model_extract":
            # No adapter, key loader, provider request or paid fallback exists here.
            # A future admitted model implementation requires its own authorization
            # and receipt contract for actual responses, usage and measured charges.
            tasks.finish(
                task.job_id,
                token,
                "blocked",
                None,
                "MODEL_EXECUTION_DISABLED",
            )
            return True
        result = validate_draft(source.packet, source.draft_json, source.provider_id)
        if result != source.result:
            raise StoreUnavailable("Historical validator semantics changed")
        if lost.is_set():
            raise DocumentTaskLeaseLost("Document lease lost")
        tasks.stage(task.job_id, token, "archiving")
        tasks.finish(task.job_id, token, "completed", result, None)
    except DocumentTaskLeaseLost:
        # Recovery belongs to a new fenced claim; this owner cannot publish.
        pass
    except (StoreUnavailable, SQLAlchemyError, ValueError):
        try:
            tasks.finish(task.job_id, token, "failed", None, "DOCUMENT_INPUT_UNAVAILABLE")
        except DocumentTaskLeaseLost:
            pass
    finally:
        stop.set()
        thread.join(timeout=10)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--forever", action="store_true")
    parser.add_argument("--worker-id", default="document-worker-" + uuid4().hex[:12])
    parser.add_argument("--poll-seconds", type=float, default=2)
    args = parser.parse_args(argv)
    if not 0.1 <= args.poll_seconds <= 60 or not 1 <= len(args.worker_id) <= 128:
        parser.error("Invalid document worker configuration")
    try:
        store = get_store()
        store.check_ready()
        with WorkerSessionMonitor(
            store.engine,
            args.worker_id,
            "document_validation",
            "forever" if args.forever else "once",
        ) as monitor:
            while True:
                monitor.check()
                processed = process_document_once(store.engine, args.worker_id)
                monitor.check()
                if not args.forever:
                    print("Document task processed" if processed else "No claimable document task")
                    return 0
                if not processed:
                    monitor.wait(args.poll_seconds)
    except KeyboardInterrupt:
        return 0
    except (SQLAlchemyError, StoreUnavailable, DocumentTaskLeaseLost, OSError, ValueError):
        print("Document worker stopped; unfinished tasks remain recoverable")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

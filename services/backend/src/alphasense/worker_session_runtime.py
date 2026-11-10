"""Process heartbeat independent of job leases; no provider or credential access."""

import hashlib
import os
from pathlib import Path
from threading import Event, Thread
from types import TracebackType
from typing import Literal, Self
from uuid import uuid4

from sqlalchemy import Engine

from alphasense.db import StoreUnavailable
from alphasense.worker_session_contracts import (
    WorkerErrorCode,
    WorkerKind,
    WorkerMode,
    WorkerSessionStart,
    WorkerStopReason,
)
from alphasense.worker_sessions import WorkerSessionStore

HEARTBEAT_SECONDS = 10
SHUTDOWN_JOIN_SECONDS = 1


class WorkerMonitorFailed(StoreUnavailable):
    """Monitoring failed; stop claiming additional work without leaking details."""


def runtime_fingerprint(kind: WorkerKind) -> str:
    root = Path(__file__).parent
    names = (
        "worker_session_runtime.py",
        "worker_sessions.py",
        "worker_session_contracts.py",
        {
            "sec_import": "task_worker.py",
            "document_validation": "document_task_worker.py",
            "sec_scheduler": "sec_scheduler.py",
        }[kind],
    )
    digest = hashlib.sha256()
    for name in names:
        digest.update(name.encode("ascii") + b"\x00" + (root / name).read_bytes())
    return digest.hexdigest()


class WorkerSessionMonitor:
    def __init__(self, engine: Engine, worker_id: str, kind: WorkerKind, mode: WorkerMode):
        self.store = WorkerSessionStore(engine)
        self.registration = WorkerSessionStart(
            session_id=uuid4(),
            worker_id=worker_id,
            kind=kind,
            mode=mode,
            process_id=os.getpid(),
            implementation_sha256=runtime_fingerprint(kind),
        )
        self._stop = Event()
        self._failed = Event()
        self._thread = Thread(target=self._heartbeat, name="worker-session-heartbeat", daemon=True)

    def __enter__(self) -> Self:
        # Registration must commit before the first queue claim.
        self.store.start(self.registration)
        try:
            self._thread.start()
        except Exception:
            self._record_stop("error", "WORKER_MONITOR_FAILED")
            raise WorkerMonitorFailed("Worker monitoring unavailable") from None
        return self

    def _heartbeat(self) -> None:
        while not self._stop.wait(HEARTBEAT_SECONDS):
            try:
                self.store.heartbeat(self.registration.session_id)
            except Exception:
                self._failed.set()
                return

    def check(self) -> None:
        if self._failed.is_set():
            raise WorkerMonitorFailed("Worker monitoring unavailable")

    def wait(self, seconds: float) -> None:
        self._failed.wait(seconds)
        self.check()

    def _record_stop(self, reason: WorkerStopReason, code: WorkerErrorCode | None) -> bool:
        try:
            self.store.stop(self.registration.session_id, reason, code)
            return True
        except Exception:
            # A failed receipt leaves the session to become stale. In particular,
            # never replace the original runtime exception with a database error.
            return False

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        self._stop.set()
        self._thread.join(timeout=SHUTDOWN_JOIN_SECONDS)
        if self._thread.is_alive():
            # A blocked heartbeat may still commit later. Do not race it with a
            # fictional clean stop; the process exits and stale detection applies.
            if exc_type is None:
                raise WorkerMonitorFailed("Worker monitoring unavailable")
            return False
        reason: WorkerStopReason
        code: WorkerErrorCode | None
        if exc_type is not None and issubclass(exc_type, KeyboardInterrupt):
            reason, code = "interrupted", None
        elif self._failed.is_set():
            reason, code = "error", "WORKER_MONITOR_FAILED"
        elif exc_type is not None:
            reason, code = "error", "WORKER_RUNTIME_FAILED"
        else:
            reason, code = "completed", None
        recorded = self._record_stop(reason, code)
        if exc_type is None and (not recorded or self._failed.is_set()):
            raise WorkerMonitorFailed("Worker monitoring unavailable")
        return False

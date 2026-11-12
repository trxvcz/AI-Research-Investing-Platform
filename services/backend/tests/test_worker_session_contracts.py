"""A liveness observation cannot extend its own freshness or hide a stopped process."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from alphasense.worker_session_contracts import WorkerSessionRecord


def observed(**changes: object) -> WorkerSessionRecord:
    now = datetime(2026, 11, 10, tzinfo=UTC)
    values = {
        "session_id": uuid4(),
        "worker_id": "local-documents",
        "kind": "document_validation",
        "mode": "forever",
        "process_id": 123,
        "implementation_sha256": "a" * 64,
        "started_at": now - timedelta(minutes=1),
        "heartbeat_at": now,
        "stopped_at": None,
        "stop_reason": None,
        "error_code": None,
        "status": "online",
        "observed_at": now,
        "contact_expires_at": now + timedelta(seconds=45),
    }
    values.update(changes)
    return WorkerSessionRecord.model_validate(values)


def test_contact_expires_at_exact_boundary_and_stopped_overrides_stale() -> None:
    first = observed()
    deadline = first.contact_expires_at
    assert observed(observed_at=deadline - timedelta(microseconds=1)).status == "online"
    assert observed(observed_at=deadline, status="stale").status == "stale"
    assert (
        observed(
            observed_at=deadline,
            stopped_at=first.heartbeat_at,
            stop_reason="completed",
            status="stopped",
        ).status
        == "stopped"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"process_id": True},
        {"process_id": 0},
        {"kind": "gemini-agent"},
        {"status": "stopped"},
        {"status": "stale"},
        {"error_code": "user-secret"},
        {"stop_reason": "error"},
        {"contact_expires_at": datetime(2026, 11, 10, 0, 0, 46, tzinfo=UTC)},
    ],
)
def test_invalid_metadata_and_fictitious_status_are_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        observed(**changes)

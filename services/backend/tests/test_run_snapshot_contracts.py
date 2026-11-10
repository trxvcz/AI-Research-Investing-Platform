"""Exact-byte and state contracts, without executing research or retrieving sources."""

import base64
import hashlib
import json
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import TypeAdapter, ValidationError

from alphasense.run_contracts import RunCommand, RunCreate, RunState
from alphasense.schemas import ROOT
from alphasense.snapshot_contracts import MAX_BYTES, SnapshotCreate


def snapshot_payload(raw: bytes = b'{ "synthetic":true, "value":0 }\r\n') -> dict:
    return {
        "schema_version": "1.0",
        "snapshot_id": str(uuid4()),
        "instrument_id": "4fd132ae-72ce-4265-967f-e37756c7a69e",
        "data_origin": "synthetic",
        "source_id": "synthetic-demo",
        "source_url": None,
        "license": "generated fixture",
        "as_of": "2024-02-01T00:00:00Z",
        "available_at": "2024-01-16T00:00:00Z",
        "retrieved_at": "2024-01-16T00:00:00Z",
        "media_type": "application/json",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "byte_length": len(raw),
        "content_base64": base64.b64encode(raw).decode("ascii"),
    }


def run_payload() -> dict:
    return {
        "schema_version": "1.0",
        "run_id": str(uuid4()),
        "instrument_id": "4fd132ae-72ce-4265-967f-e37756c7a69e",
        "as_of": "2024-02-01T00:00:00Z",
        "snapshot_ids": [str(uuid4())],
    }


def test_exact_json_bytes_preserve_whitespace_and_binary() -> None:
    for raw in [b'{"value":0}\n', b'{ "value":0 }\r\n', b"\x00\xff\xfe\x80"]:
        payload = snapshot_payload(raw)
        parsed = SnapshotCreate.model_validate_json(json.dumps(payload))
        assert parsed.raw_bytes() == raw
        schema = json.loads((ROOT / "contracts/v1/snapshot-create.schema.json").read_text("utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)


@pytest.mark.parametrize("case", ["hash", "length", "base64", "canonical", "empty", "oversize"])
def test_content_integrity_rejects_bad_payload(case: str) -> None:
    payload = snapshot_payload()
    if case == "hash":
        payload["sha256"] = "0" * 64
    elif case == "length":
        payload["byte_length"] += 1
    elif case == "base64":
        payload["content_base64"] = "!!not64!!"
    elif case == "canonical":
        payload = snapshot_payload(b"\x00")
        payload["content_base64"] = "AB=="
    elif case == "empty":
        payload = snapshot_payload(b"")
    else:
        payload = snapshot_payload(b"x" * (MAX_BYTES + 1))
    with pytest.raises(ValidationError):
        SnapshotCreate.model_validate(payload)


def test_unknown_availability_is_null_not_a_backdated_timestamp() -> None:
    payload = snapshot_payload()
    payload["available_at"] = None
    assert SnapshotCreate.model_validate(payload).available_at is None


@pytest.mark.parametrize("field", ["source_id", "license"])
def test_ascii_controls_in_metadata_are_not_archived(field: str) -> None:
    payload = snapshot_payload()
    payload[field] = "private\x00field"
    with pytest.raises(ValidationError):
        SnapshotCreate.model_validate(payload)


def test_snapshot_time_order_and_live_source_rules() -> None:
    payload = snapshot_payload()
    payload["available_at"] = "2024-02-02T00:00:00Z"
    with pytest.raises(ValidationError):
        SnapshotCreate.model_validate(payload)
    payload = snapshot_payload()
    payload["data_origin"] = "live"
    with pytest.raises(ValidationError):
        SnapshotCreate.model_validate(payload)


def test_run_inputs_are_unique_and_bounded() -> None:
    payload = run_payload()
    assert RunCreate.model_validate(payload).pipeline_version == "manual-research-v1"
    payload["snapshot_ids"] *= 2
    with pytest.raises(ValidationError):
        RunCreate.model_validate(payload)
    payload["snapshot_ids"] = [str(uuid4()) for _ in range(33)]
    with pytest.raises(ValidationError):
        RunCreate.model_validate(payload)


@pytest.mark.parametrize(
    "change",
    [
        {"expected_sequence": True},
        {"expected_sequence": 0},
        {"actor": "bad\x00actor"},
        {"action": "execute_python"},
    ],
)
def test_commands_are_strict_and_cannot_request_arbitrary_execution(change) -> None:
    command = {
        "action": "start",
        "request_id": str(uuid4()),
        "expected_sequence": 1,
        "actor": "test",
    }
    command.update(change)
    with pytest.raises(ValidationError):
        TypeAdapter(RunCommand).validate_python(command)


def test_state_cannot_claim_completion_without_report_or_skip_steps() -> None:
    payload = run_payload()
    payload.pop("schema_version")
    payload.update(
        pipeline_version="manual-research-v1",
        data_origin="synthetic",
        sequence=1,
        status="queued",
        current_step="data",
        completed_steps=[],
        error_code=None,
        error_reason=None,
        report_revision_id=None,
        report_status=None,
        created_at="2026-10-30T00:00:00Z",
        updated_at="2026-10-30T00:00:00Z",
    )
    assert RunState.model_validate(payload).status == "queued"
    payload["status"] = "completed"
    with pytest.raises(ValidationError):
        RunState.model_validate(payload)
    payload.update(status="running", completed_steps=["technical"], current_step="report")
    with pytest.raises(ValidationError):
        RunState.model_validate(payload)

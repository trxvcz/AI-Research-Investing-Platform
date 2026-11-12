"""Pure golden and adversarial tests for the bounded deterministic research engine."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from alphasense.contracts import ResearchInput
from alphasense.instrument_contracts import InstrumentRecord
from alphasense.report_contracts import ReportRevision
from alphasense.run_contracts import RunState
from alphasense.snapshot_contracts import SnapshotRecord
from alphasense.worker_engine import (
    WorkerInputError,
    compile_report,
    fundamental_section,
    load_input,
    technical_section,
)

GIT_SHA = "6d7e7269fe72199c365b157a456ddab399f85e93"
IMPLEMENTATION = hashlib.sha256(b"synthetic-worker-test-implementation").hexdigest()
INSTRUMENT_ID = UUID("50bb7e95-023a-4ceb-a583-5e74e96a66ca")
RUN_ID = UUID("9e34cbef-9217-4607-b806-dc6ed27decda")
SNAPSHOT_ID = UUID(int=1)


def observation(metric: str, value: float = 100, **changes: Any) -> dict[str, Any]:
    result = {
        "metric": metric,
        "unit": "currency",
        "currency": "USD",
        "period_start": "2023-01-01T00:00:00Z",
        "period_end": "2023-12-31T00:00:00Z",
        "status": "available",
        "value": value,
        "source_id": "synthetic-worker-source",
        "snapshot_id": str(UUID(int=1)),
        "event_time": "2024-01-15T00:00:00Z",
        "available_at": "2024-01-31T00:00:00Z",
    }
    result.update(changes)
    return result


def close(day: int, value: float, **changes: Any) -> dict[str, Any]:
    timestamp = f"2024-01-{day:02d}T00:00:00Z"
    return observation(
        "close",
        value,
        unit="currency_per_unit",
        period_start=timestamp,
        period_end=timestamp,
        event_time=timestamp,
        **changes,
    )


def input_data(observations: list[dict[str, Any]]) -> ResearchInput:
    return ResearchInput.model_validate(
        {
            "schema_version": "1.0",
            "instrument_id": str(INSTRUMENT_ID),
            "asset_type": "equity",
            "as_of": "2024-02-01T00:00:00Z",
            "data_origin": "synthetic",
            "observations": observations,
        }
    )


def bundle(
    observations: list[dict[str, Any]] | None = None,
    snapshot_id: UUID = SNAPSHOT_ID,
    raw: bytes | None = None,
    **metadata_changes: Any,
) -> tuple[RunState, InstrumentRecord, list[tuple[SnapshotRecord, bytes]]]:
    rows = (
        observations
        if observations is not None
        else [
            observation("revenue", 100),
            observation("net_income", 25),
            close(28, 1),
            close(29, 2),
            close(30, 3),
        ]
    )
    rows = deepcopy(rows)
    for row in rows:
        if row["status"] == "available":
            row["snapshot_id"] = str(snapshot_id)
    content = raw if raw is not None else input_data(rows).model_dump_json().encode("utf-8")
    instrument = InstrumentRecord.model_validate(
        {
            "schema_version": "1.0",
            "instrument_id": str(INSTRUMENT_ID),
            "symbol": "SYNTH-WORKER",
            "exchange_mic": "XNAS",
            "currency": "USD",
            "display_name": "Synthetic worker fixture",
            "asset_type": "equity",
            "data_origin": "synthetic",
            "as_of": "2024-02-01T00:00:00Z",
            "available_at": "2024-01-01T00:00:00Z",
            "source_id": "synthetic-registry",
            "source_url": None,
            "license": "generated fixture",
            "created_at": "2024-02-02T00:00:00Z",
        }
    )
    metadata = {
        "schema_version": "1.0",
        "snapshot_id": str(snapshot_id),
        "instrument_id": str(INSTRUMENT_ID),
        "data_origin": "synthetic",
        "source_id": "synthetic-worker-source",
        "source_url": None,
        "license": "generated fixture",
        "as_of": "2024-02-01T00:00:00Z",
        "available_at": "2024-01-31T00:00:00Z",
        "retrieved_at": "2024-02-02T00:00:00Z",
        "media_type": "application/json",
        "sha256": hashlib.sha256(content).hexdigest(),
        "byte_length": len(content),
        "created_at": "2024-02-02T00:00:00Z",
    }
    metadata.update(metadata_changes)
    record = SnapshotRecord.model_validate(metadata)
    state = RunState.model_validate(
        {
            "run_id": str(RUN_ID),
            "instrument_id": str(INSTRUMENT_ID),
            "as_of": "2024-02-01T00:00:00Z",
            "snapshot_ids": [str(snapshot_id)],
            "pipeline_version": "deterministic-research-v1",
            "data_origin": "synthetic",
            "sequence": 2,
            "status": "running",
            "current_step": "data",
            "completed_steps": [],
            "error_code": None,
            "error_reason": None,
            "report_revision_id": None,
            "report_status": None,
            "created_at": "2024-02-03T00:00:00Z",
            "updated_at": "2024-02-03T00:00:00Z",
        }
    )
    return state, instrument, [(record, content)]


def test_golden_margin_sma_and_stable_sealed_report() -> None:
    state, instrument, snapshots = bundle()
    data = load_input(state, instrument, snapshots)
    fundamental = fundamental_section(data)
    ratio = [item for item in fundamental.findings if item.method == "ratio-net-margin-v1"]
    assert len(ratio) == 1 and "net_margin=0.25 (ratio)" in ratio[0].text
    assert ratio[0].observation_indexes == [1, 0]
    technical = technical_section(data)
    assert "last3_observation_sma=2.0 USD/unit" in technical.findings[0].text
    assert technical.findings[0].observation_indexes == [2, 3, 4]
    report = compile_report(state, instrument, snapshots, GIT_SHA, IMPLEMENTATION)
    assert report.status == "partial"
    assert report.report_id == uuid5(NAMESPACE_URL, "alphasense:worker-report:" + str(RUN_ID))
    assert report.revision_id == uuid5(NAMESPACE_URL, "alphasense:worker-revision:" + str(RUN_ID))
    assert report.generated_at_utc == state.created_at
    assert report.model_provenance is None and report.chart_artifact_ids == []
    assert report.sources[0].sha256 == snapshots[0][0].sha256
    assert IMPLEMENTATION in report.limitations[0]
    assert ReportRevision.model_validate_json(report.model_dump_json()) == report
    assert (
        compile_report(state, instrument, snapshots, GIT_SHA, IMPLEMENTATION).checksum
        == report.checksum
    )


@pytest.mark.parametrize(
    "revenue,income,expected", [(0, 25, None), (100, 0, "0.0"), (-100, 25, "-0.25")]
)
def test_zero_is_preserved_and_zero_denominator_is_not_a_fake_ratio(
    revenue: float, income: float, expected: str | None
) -> None:
    section = fundamental_section(
        input_data([observation("revenue", revenue), observation("net_income", income)])
    )
    calculations = [item for item in section.findings if item.kind == "calculation"]
    if expected is None:
        assert calculations == [] and "revenue is zero" in str(section.reason)
        assert any("revenue=0.0" in item.text for item in section.findings)
    else:
        assert f"net_margin={expected}" in calculations[0].text
    assert section.status == "partial"


def test_ambiguous_or_missing_latest_period_never_uses_older_ratio() -> None:
    rows = [observation("revenue", 100), observation("net_income", 25)]
    ambiguous = [*rows, observation("revenue", 50, period_start="2023-10-01T00:00:00Z")]
    section = fundamental_section(input_data(ambiguous))
    assert all(item.kind != "calculation" for item in section.findings)
    assert "ambiguous" in str(section.reason)
    missing = {
        "metric": "revenue",
        "unit": "currency",
        "currency": "USD",
        "period_start": "2024-01-01T00:00:00Z",
        "period_end": "2024-01-31T00:00:00Z",
        "status": "missing",
        "value": None,
        "reason": "No latest-period input",
    }
    section = fundamental_section(input_data([*rows, missing]))
    assert all(item.kind != "calculation" for item in section.findings)


@pytest.mark.parametrize("revenue,income", [(1e-308, 1e308), (1e308, 5e-324)])
def test_unrepresentable_margin_is_an_explicit_gap(revenue: float, income: float) -> None:
    section = fundamental_section(
        input_data([observation("revenue", revenue), observation("net_income", income)])
    )
    assert all(item.kind != "calculation" for item in section.findings)
    assert "not representable" in str(section.reason)


def test_wrong_units_and_currency_do_not_generate_facts_or_ratio() -> None:
    data = input_data(
        [observation("revenue", unit="shares"), observation("net_income", currency=None)]
    )
    section = fundamental_section(data)
    assert section.status == "blocked" and section.findings == []


def test_facts_are_capped_at_forty() -> None:
    rows = []
    start = datetime(2020, 1, 1, tzinfo=UTC)
    for index in range(60):
        end = (start + timedelta(days=index)).isoformat()
        rows.append(observation("revenue", index, period_start=end, period_end=end))
    facts = fundamental_section(input_data(rows)).findings
    assert len(facts) == 40
    assert all(item.kind == "fact" for item in facts)


def test_technical_uses_last_three_observations_not_input_order_or_days() -> None:
    data = input_data([close(30, 4), close(10, 100), close(25, 2), close(29, 3)])
    result = technical_section(data)
    assert result.status == "partial"
    assert result.findings[0].observation_indexes == [2, 3, 0]
    assert "sma=3.0" in result.findings[0].text
    assert "not three days" in str(result.reason)


@pytest.mark.parametrize(
    "change", ["short", "negative", "currency", "unit", "period", "duplicate_time"]
)
def test_technical_blocks_unsuitable_price_series(change: str) -> None:
    rows = [close(28, 1), close(29, 2), close(30, 3)]
    if change == "short":
        rows.pop()
    elif change == "negative":
        rows[0]["value"] = 0
    elif change == "currency":
        rows[0]["currency"] = "EUR"
    elif change == "unit":
        rows[0]["unit"] = "currency"
    elif change == "period":
        rows[0]["period_start"] = "2024-01-27T00:00:00Z"
    else:
        rows[0]["period_start"] = rows[1]["period_start"]
        rows[0]["period_end"] = rows[1]["period_end"]
        rows[0]["event_time"] = rows[1]["event_time"]
        rows[0]["currency"] = "EUR"
    result = technical_section(input_data(rows))
    assert result.status == "blocked" and result.findings == []


def test_finite_sma_avoids_sum_overflow() -> None:
    result = technical_section(input_data([close(28, 1e308), close(29, 1e308), close(30, 1e308)]))
    assert result.status == "partial"
    assert "sma=1e+308" in result.findings[0].text


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version":"1.0","schema_version":"1.0"}',
        b'{"a":{"value":1,"value":2}}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b'{"a":-Infinity}',
        b'{"a":1e999}',
        b"[]",
        b"\xff",
        b"{broken",
    ],
)
def test_bad_json_duplicate_keys_and_nonfinite_values_fail_closed(raw: bytes) -> None:
    state, instrument, snapshots = bundle(raw=raw)
    with pytest.raises(WorkerInputError) as error:
        load_input(state, instrument, snapshots)
    assert str(error.value) == error.value.code
    assert error.value.code in {"INVALID_JSON", "INPUT_SCHEMA"}


@pytest.mark.parametrize(
    "case", ["bytes", "missing", "duplicate", "format", "unknown_availability", "late_retrieval"]
)
def test_archive_gates_are_rechecked_without_trusting_callers(case: str) -> None:
    state, instrument, snapshots = bundle()
    if case == "bytes":
        snapshots[0] = (snapshots[0][0], snapshots[0][1] + b" ")
    elif case == "missing":
        snapshots = []
    elif case == "duplicate":
        snapshots *= 2
    else:
        field, value = {
            "format": ("media_type", "application/pdf"),
            "unknown_availability": ("available_at", None),
            "late_retrieval": ("retrieved_at", "2024-02-04T00:00:00Z"),
        }[case]
        payload = snapshots[0][0].model_dump(mode="json")
        payload[field] = value
        snapshots[0] = (SnapshotRecord.model_validate(payload), snapshots[0][1])
    with pytest.raises(WorkerInputError):
        load_input(state, instrument, snapshots)


@pytest.mark.parametrize(
    "case", ["identity", "source", "snapshot", "availability", "retrieval_floor"]
)
def test_packet_identity_and_provenance_are_not_invented(case: str) -> None:
    state, instrument, snapshots = bundle()
    payload = json.loads(snapshots[0][1])
    if case == "identity":
        payload["instrument_id"] = str(UUID(int=999))
    elif case == "source":
        payload["observations"][0]["source_id"] = "foreign-source"
    elif case == "snapshot":
        payload["observations"][0]["snapshot_id"] = str(UUID(int=999))
    elif case == "availability":
        payload["observations"][0]["available_at"] = "2024-01-30T00:00:00Z"
    else:
        payload["observations"][0]["available_at"] = "2024-02-01T00:00:00Z"
        metadata = snapshots[0][0].model_dump(mode="json")
        metadata["retrieved_at"] = "2024-01-31T00:00:00Z"
        snapshots[0] = (SnapshotRecord.model_validate(metadata), snapshots[0][1])
    raw = json.dumps(payload).encode("utf-8")
    metadata = snapshots[0][0].model_dump(mode="json")
    metadata.update(sha256=hashlib.sha256(raw).hexdigest(), byte_length=len(raw))
    snapshots[0] = (SnapshotRecord.model_validate(metadata), raw)
    with pytest.raises(WorkerInputError):
        load_input(state, instrument, snapshots)


def test_combined_inputs_are_validated_for_duplicate_contexts() -> None:
    state, instrument, first = bundle([observation("revenue")])
    _state, _instrument, second = bundle([observation("revenue")], snapshot_id=UUID(int=2))
    state.snapshot_ids.append(UUID(int=2))
    with pytest.raises(WorkerInputError, match="COMBINED_INPUT"):
        load_input(state, instrument, first + second)


def test_packet_order_is_frozen_and_missing_data_are_not_zero() -> None:
    state, instrument, first = bundle([observation("revenue")])
    missing = {
        "metric": "net_income",
        "unit": "currency",
        "currency": "USD",
        "period_start": "2023-01-01T00:00:00Z",
        "period_end": "2023-12-31T00:00:00Z",
        "status": "missing",
        "value": None,
        "reason": "No input",
    }
    _other_state, _instrument, second = bundle([missing], snapshot_id=UUID(int=2))
    state.snapshot_ids.append(UUID(int=2))
    report = compile_report(state, instrument, first + second, GIT_SHA, IMPLEMENTATION)
    reverse = compile_report(state, instrument, second + first, GIT_SHA, IMPLEMENTATION)
    assert report.checksum == reverse.checksum
    assert report.input.observations[1].value is None
    assert len(report.sources) == 1


def test_no_supported_data_produces_blocked_report_without_fake_results() -> None:
    missing = {
        "metric": "revenue",
        "unit": "currency",
        "currency": "USD",
        "period_start": "2023-01-01T00:00:00Z",
        "period_end": "2023-12-31T00:00:00Z",
        "status": "missing",
        "value": None,
        "reason": "No input",
    }
    state, instrument, snapshots = bundle([missing])
    report = compile_report(state, instrument, snapshots, GIT_SHA, IMPLEMENTATION)
    assert report.status == "blocked" and report.sources == []
    assert report.fundamental_section.findings == report.technical_section.findings == []


@pytest.mark.parametrize("case", ["git", "implementation", "future_cutoff", "manual"])
def test_invalid_pipeline_context_never_guesses_metadata(case: str) -> None:
    state, instrument, snapshots = bundle()
    git, implementation = GIT_SHA, IMPLEMENTATION
    if case == "git":
        git = "unknown"
    elif case == "implementation":
        implementation = "unknown"
    elif case == "future_cutoff":
        state.created_at = datetime(2024, 1, 1, tzinfo=UTC)
    else:
        state.pipeline_version = "manual-research-v1"
    with pytest.raises(WorkerInputError):
        compile_report(state, instrument, snapshots, git, implementation)

"""Independent fixtures and adversarial inputs for v1 and legacy schemas."""

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from alphasense.contracts import AvailableObservation, ResearchInput, summarize
from alphasense.schemas import MODELS, ROOT, export

FIXTURE = Path(__file__).parent / "fixtures" / "research-input.synthetic.json"


@pytest.fixture
def payload() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def validator() -> Draft202012Validator:
    schema = json.loads((ROOT / "contracts/v1/research-input.schema.json").read_text("utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_fixture_preserves_zero_missing_and_declared_origin(payload: dict[str, Any]) -> None:
    validator().validate(payload)
    parsed = ResearchInput.model_validate_json(json.dumps(payload))
    first, second = parsed.observations
    assert isinstance(first, AvailableObservation)
    assert first.value == 0
    assert second.value is None
    assert parsed.data_origin == "synthetic"
    result = summarize(parsed)
    assert (result.status, result.available_count, result.missing_count) == ("partial", 1, 1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("value", None),
        ("value", True),
        ("value", "100"),
        ("currency", "usd"),
        ("currency", 123),
        ("source_id", ""),
        ("snapshot_id", " "),
        ("metric", "Revenue"),
        ("metric", "revenue\n"),
        ("currency", "USD\n"),
        ("unit", "USD\n"),
        ("source_id", "source\n"),
        ("snapshot_id", "snapshot\n"),
        ("unit", ""),
        ("available_at", "2024-01-16"),
        ("available_at", "2024-01-16T00:00:00"),
        ("available_at", 1705363200),
        ("available_at", "2024-02-30T00:00:00Z"),
        ("available_at", "2024-01-16T00:00:00Z\n"),
        ("available_at", "2024-01-16T00:00:00.000000001Z"),
        ("period_end", "not a date"),
    ],
)
def test_schema_and_runtime_reject_bad_observation_fields(
    payload: dict[str, Any], field: str, value: Any
) -> None:
    payload["observations"][0][field] = value
    assert list(validator().iter_errors(payload))
    with pytest.raises(ValidationError):
        ResearchInput.model_validate(payload)


@pytest.mark.parametrize("field", ["currency", "unit", "source_id", "snapshot_id", "available_at"])
def test_required_provenance_cannot_be_omitted(payload: dict[str, Any], field: str) -> None:
    del payload["observations"][0][field]
    assert list(validator().iter_errors(payload))
    with pytest.raises(ValidationError):
        ResearchInput.model_validate(payload)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_runtime_rejects_non_finite_numbers(payload: dict[str, Any], value: float) -> None:
    payload["observations"][0]["value"] = value
    with pytest.raises(ValidationError):
        ResearchInput.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("period_start", "2024-01-01T00:00:00Z"),
        ("event_time", "2023-12-01T00:00:00Z"),
        ("available_at", "2024-01-14T00:00:00Z"),
        ("available_at", "2024-02-02T00:00:00Z"),
    ],
)
def test_semantic_chronology_cannot_be_bypassed(
    payload: dict[str, Any], field: str, value: str
) -> None:
    payload["observations"][0][field] = value
    # JSON Schema validates shape, Pydantic additionally validates relationships.
    validator().validate(payload)
    with pytest.raises(ValidationError):
        ResearchInput.model_validate(payload)


def test_as_of_uses_instant_not_lexicographic_time(payload: dict[str, Any]) -> None:
    payload["as_of"] = "2024-01-16T01:00:00+01:00"
    parsed = ResearchInput.model_validate(payload)
    assert parsed.as_of == datetime(2024, 1, 16, tzinfo=UTC)
    assert parsed.model_dump(mode="json")["as_of"] == "2024-01-16T00:00:00Z"


def test_sub_microsecond_future_cannot_be_truncated_to_as_of(payload: dict[str, Any]) -> None:
    payload["as_of"] = "2024-02-01T00:00:00.000000Z"
    payload["observations"][0]["available_at"] = "2024-02-01T00:00:00.000000001Z"
    assert list(validator().iter_errors(payload))
    with pytest.raises(ValidationError):
        ResearchInput.model_validate(payload)


def test_duplicate_context_after_timezone_normalization_is_rejected(
    payload: dict[str, Any],
) -> None:
    duplicate = deepcopy(payload["observations"][0])
    duplicate["period_start"] = "2023-01-01T01:00:00+01:00"
    payload["observations"].append(duplicate)
    with pytest.raises(ValidationError, match="duplicate"):
        ResearchInput.model_validate(payload)


@pytest.mark.parametrize("value", [0, False, "0"])
def test_absence_never_coerces_a_value_to_null(payload: dict[str, Any], value: Any) -> None:
    payload["observations"][1]["value"] = value
    assert list(validator().iter_errors(payload))
    with pytest.raises(ValidationError):
        ResearchInput.model_validate(payload)


def test_absence_requires_reason_and_cannot_claim_fake_provenance(payload: dict[str, Any]) -> None:
    payload["observations"][1]["reason"] = ""
    payload["observations"][1]["source_id"] = "invented"
    assert list(validator().iter_errors(payload))
    with pytest.raises(ValidationError):
        ResearchInput.model_validate(payload)


def test_absence_cannot_claim_future_period(payload: dict[str, Any]) -> None:
    payload["observations"][1]["period_end"] = "2024-02-02T00:00:00Z"
    with pytest.raises(ValidationError):
        ResearchInput.model_validate(payload)


@pytest.mark.parametrize("location", ["root", "observation"])
def test_unknown_fields_are_rejected_at_all_boundaries(
    payload: dict[str, Any], location: str
) -> None:
    target = payload if location == "root" else payload["observations"][0]
    target["provider"] = "paid-fallback"
    assert list(validator().iter_errors(payload))
    with pytest.raises(ValidationError):
        ResearchInput.model_validate(payload)


@pytest.mark.parametrize("observations", [[], [{}] * 1001])
def test_batch_limits(payload: dict[str, Any], observations: list[dict[str, Any]]) -> None:
    payload["observations"] = observations
    assert list(validator().iter_errors(payload))
    with pytest.raises(ValidationError):
        ResearchInput.model_validate(payload)


def test_origin_is_independent_of_completeness(payload: dict[str, Any]) -> None:
    payload["data_origin"] = "live"
    result = summarize(ResearchInput.model_validate(payload))
    assert result.data_origin == "live"
    assert result.status == "partial"


def test_generated_schemas_are_current_and_valid() -> None:
    export(check=True)
    files = sorted((ROOT / "contracts").rglob("*.schema.json"))
    assert len(files) == 4 + len(MODELS)
    for path in files:
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(schema)


def test_result_schema_accepts_serialized_runtime_output(payload: dict[str, Any]) -> None:
    result = summarize(ResearchInput.model_validate(payload))
    schema = json.loads((ROOT / "contracts/v1/validation-result.schema.json").read_text("utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(
        result.model_dump(mode="json")
    )

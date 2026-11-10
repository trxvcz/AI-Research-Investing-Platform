"""Registry boundaries independently exercised against exported JSON Schema."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from alphasense.instrument_contracts import InstrumentCreate
from alphasense.schemas import ROOT

FIXTURE = Path(__file__).parent / "fixtures/instrument.synthetic.json"


def sample() -> dict:
    return json.loads(FIXTURE.read_text("utf-8"))


def validator() -> Draft202012Validator:
    path = ROOT / "contracts/v1/instrument-create.schema.json"
    return Draft202012Validator(json.loads(path.read_text("utf-8")), format_checker=FormatChecker())


def test_synthetic_fixture_is_valid_and_utc_normalized() -> None:
    payload = sample()
    validator().validate(payload)
    parsed = InstrumentCreate.model_validate_json(json.dumps(payload))
    assert parsed.model_dump(mode="json") == payload
    assert parsed.data_origin == "synthetic"


@pytest.mark.parametrize(
    "field,value",
    [
        ("symbol", "demo"),
        ("symbol", "DEMO\n"),
        ("symbol", "A" * 33),
        ("exchange_mic", "nasdaq"),
        ("currency", "usd"),
        ("currency", "USD\n"),
        ("display_name", " Bad"),
        ("display_name", "Bad\n"),
        ("display_name", "bad\x00x"),
        ("source_id", "bad\x00x"),
        ("license", "bad\tx"),
        ("source_url", "ftp://example.invalid/source"),
        ("source_url", "https://example.invalid/\x00x"),
        ("as_of", "2024-02-01"),
        ("available_at", 1700000000),
        ("as_of", "2024-02-01T00:00:00.0000001Z"),
        ("instrument_id", "4fd132ae72ce4265967fe37756c7a69e"),
    ],
)
def test_model_and_schema_reject_bad_shapes(field, value) -> None:
    payload = sample()
    payload[field] = value
    assert list(validator().iter_errors(payload))
    with pytest.raises(ValidationError):
        InstrumentCreate.model_validate(payload)


@pytest.mark.parametrize("case", ["future_available", "equity_no_exchange", "live_no_source"])
def test_semantic_requirements(case) -> None:
    payload = sample()
    if case == "future_available":
        payload["available_at"] = "2024-02-02T00:00:00Z"
    elif case == "equity_no_exchange":
        payload["exchange_mic"] = None
    else:
        payload["data_origin"] = "live"
    with pytest.raises(ValidationError):
        InstrumentCreate.model_validate(payload)


def test_commodity_without_mic_is_explicit_null() -> None:
    payload = sample()
    payload.update(asset_type="commodity", exchange_mic=None)
    validator().validate(payload)
    assert InstrumentCreate.model_validate(payload).exchange_mic is None


def test_missing_fields_unknown_fields_and_mutated_model() -> None:
    payload = sample()
    del payload["currency"]
    assert list(validator().iter_errors(payload))
    with pytest.raises(ValidationError):
        InstrumentCreate.model_validate(payload)
    payload = deepcopy(sample())
    payload["paid_fallback"] = True
    assert list(validator().iter_errors(payload))
    with pytest.raises(ValidationError):
        InstrumentCreate.model_validate(payload)

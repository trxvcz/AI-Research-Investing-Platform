"""Compatibility must never manufacture missing point-in-time provenance."""

import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from alphasense.legacy import (
    InvalidReportError,
    LegacyInspection,
    V1Inspection,
    _legacy_validator,
    inspect_report,
)

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def legacy() -> dict[str, Any]:
    """A synthetic M0 document, not evidence from a financial provider."""
    return {
        "id": "synthetic-legacy-report",
        "parent_id": None,
        "created_at": "2026-10-30T00:00:00Z",
        "status": "demo",
        "input_hash": "synthetic-input-hash",
        "code_version": "starter-0.1.0",
        "analysis": {
            "asset_id": "DEMO-EQUITY",
            "asset_type": "equity",
            "as_of": "2024-01-10T00:00:00Z",
            "fundamental": {"method": "synthetic fixture", "net_margin": 0},
            "technical": {"signal": "none; synthetic fixture"},
            "sources": ["synthetic-demo"],
            "status": "demo",
        },
        "trace": ["data", "fundamental", "technical", "report", "reviewer"],
        "charts": ["chart.svg"],
        "warnings": ["Synthetic data only"],
    }


def test_legacy_stays_unmigrated_without_mutating_payload(legacy: dict[str, Any]) -> None:
    before = deepcopy(legacy)
    result = inspect_report(legacy)
    assert isinstance(result, LegacyInspection)
    assert result.model_dump(mode="json") == {
        "format": "legacy-m0",
        "report_id": "synthetic-legacy-report",
        "legacy_status": "demo",
        "migration_status": "blocked_missing_provenance",
        "missing_fields": [
            "observation_available_at",
            "observation_periods",
            "snapshot_provenance",
        ],
    }
    assert legacy == before
    assert "schema_version" not in result.model_dump()
    assert "data_origin" not in result.model_dump()
    assert "available_at" not in result.model_dump()


@pytest.mark.parametrize("status", ["demo", "complete", "partial", "blocked", "failed"])
def test_legacy_status_is_preserved_but_never_promoted(legacy: dict[str, Any], status: str) -> None:
    legacy["status"] = status
    result = inspect_report(legacy)
    assert isinstance(result, LegacyInspection)
    assert result.legacy_status == status
    assert result.migration_status == "blocked_missing_provenance"
    assert "status" not in result.model_dump()


@pytest.mark.parametrize("version", [None, "0.1", "2.0", "1.0", 1])
def test_explicit_version_never_falls_back_to_m0(legacy: dict[str, Any], version: Any) -> None:
    legacy["schema_version"] = version
    with pytest.raises(InvalidReportError, match="^Invalid report data$"):
        inspect_report(legacy)


@pytest.mark.parametrize(
    ("where", "value"),
    [
        ("created_at", "not a date"),
        ("created_at", "2026-02-30T00:00:00Z"),
        ("created_at", "2026-10-30"),
        ("as_of", "2024-01-10T00:00:00"),
        ("as_of", "2099-99-99T00:00:00Z"),
    ],
)
def test_legacy_format_validation_rejects_bad_dates(
    legacy: dict[str, Any], where: str, value: str
) -> None:
    target = legacy["analysis"] if where == "as_of" else legacy
    target[where] = value
    with pytest.raises(InvalidReportError, match="^Invalid report data$"):
        inspect_report(legacy)


def test_future_legacy_dates_do_not_manufacture_availability(legacy: dict[str, Any]) -> None:
    # M0 has no observation-level chronology contract. Accepting its shape does
    # not authorize history/backtests, even when its declared as_of is future.
    legacy["analysis"]["as_of"] = "2099-01-01T00:00:00Z"
    result = inspect_report(legacy)
    assert isinstance(result, LegacyInspection)
    assert result.migration_status == "blocked_missing_provenance"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_numbers_cannot_hide_in_legacy_open_metrics(
    legacy: dict[str, Any], value: float
) -> None:
    legacy["analysis"]["fundamental"]["private_metric"] = value
    with pytest.raises(InvalidReportError, match="^Invalid report data$"):
        inspect_report(legacy)


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong_type"])
def test_malformed_reports_raise_generic_error(legacy: dict[str, Any], mutation: str) -> None:
    if mutation == "missing":
        del legacy["analysis"]
    elif mutation == "extra":
        legacy["PRIVATE-DOCUMENT"] = "PRIVATE-CONTENT"
    else:
        legacy["analysis"]["fundamental"] = "PRIVATE-CONTENT"
    with pytest.raises(InvalidReportError) as caught:
        inspect_report(legacy)
    assert str(caught.value) == "Invalid report data"
    assert "PRIVATE" not in str(caught.value)


def test_legacy_reader_rejects_non_json_python_values(legacy: dict[str, Any]) -> None:
    legacy["analysis"]["fundamental"]["unsupported"] = object()
    with pytest.raises(InvalidReportError, match="^Invalid report data$"):
        inspect_report(legacy)


def test_legacy_schema_never_fetches_external_resources() -> None:
    from referencing.exceptions import NoSuchResource

    with pytest.raises(NoSuchResource):
        _legacy_validator()._registry.get_or_retrieve("https://example.invalid/private-schema")


def test_schema_infrastructure_failures_are_not_report_errors(
    legacy: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    import alphasense.legacy as module

    def unavailable() -> None:
        raise OSError("schema unavailable")

    monkeypatch.setattr(module, "_legacy_validator", unavailable)
    with pytest.raises(OSError, match="schema unavailable"):
        inspect_report(legacy)


def test_original_node_report_remains_byte_identical_after_inspection(tmp_path: Path) -> None:
    directory = tmp_path / "legacy-reports"
    # Node writes only within this test's temporary directory, never artifacts/.
    script = (
        "import {run} from './services/runtime/demo.mjs';"
        "const report=await run(process.argv[1]);console.log(report.id);"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(directory)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    report_id = result.stdout.strip()
    report_directory = directory / report_id
    before = {p.name: p.read_bytes() for p in report_directory.iterdir()}
    report = json.loads(before["report.json"])
    inspected = inspect_report(report)
    assert isinstance(inspected, LegacyInspection)
    assert inspected.report_id == report_id
    assert {p.name: p.read_bytes() for p in report_directory.iterdir()} == before
    assert sorted(p.name for p in directory.iterdir()) == [report_id]


def test_fixed_schema_is_valid_and_has_no_external_refs() -> None:
    validator = _legacy_validator()

    def refs(value: Any) -> list[str]:
        if isinstance(value, dict):
            direct = [value["$ref"]] if "$ref" in value else []
            return direct + [ref for child in value.values() for ref in refs(child)]
        if isinstance(value, list):
            return [ref for child in value for ref in refs(child)]
        return []

    assert all(ref.startswith("#") for ref in refs(validator.schema))


def test_valid_v1_inspection_returns_only_verified_metadata() -> None:
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "report.synthetic.json").read_text(encoding="utf-8")
    )
    before = deepcopy(payload)
    result = inspect_report(payload)
    assert isinstance(result, V1Inspection)
    assert result.model_dump(mode="json") == {
        "format": "v1",
        "schema_version": "1.0",
        "report_id": payload["report_id"],
        "revision_id": payload["revision_id"],
        "revision": payload["revision"],
        "status": payload["status"],
        "data_origin": payload["input"]["data_origin"],
        "checksum": payload["checksum"],
    }
    assert payload == before
    assert "input" not in result.model_dump()
    assert "sources" not in result.model_dump()


@pytest.mark.parametrize("format_name", ["legacy-m0", "v1"])
def test_metadata_output_matches_exported_schema(legacy: dict[str, Any], format_name: str) -> None:
    payload = (
        legacy
        if format_name == "legacy-m0"
        else json.loads(
            (Path(__file__).parent / "fixtures" / "report.synthetic.json").read_text(
                encoding="utf-8"
            )
        )
    )
    result = inspect_report(payload).model_dump(mode="json")
    schema = json.loads(
        (ROOT / "contracts" / "v1" / "report-inspection.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(result)
    result["input"] = "PRIVATE-CONTENT"
    assert list(validator.iter_errors(result))

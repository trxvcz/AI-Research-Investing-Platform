"""Report integrity and research provenance gates using synthetic fixtures."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from alphasense.report_contracts import (
    DISCLAIMER,
    ReportContent,
    ReportRevision,
    canonical_sha256,
    seal_report,
)
from alphasense.schemas import ROOT

FIXTURES = Path(__file__).parent / "fixtures"


def valid_content() -> dict[str, Any]:
    observations = json.loads((FIXTURES / "research-input.synthetic.json").read_text("utf-8"))
    return {
        "schema_version": "1.0",
        "report_id": "f8550d24-5200-42fe-b715-a564af5c8c42",
        "revision_id": "72589ef2-5137-41f3-92ec-d3681e6d2e6a",
        "parent_revision_id": None,
        "revision": 1,
        "generated_at_utc": "2024-02-02T00:00:00Z",
        "input": observations,
        "status": "partial",
        "methodology_version": "synthetic-envelope-fixture-1",
        "pipeline_git_sha": "6d7e7269fe72199c365b157a456ddab399f85e93",
        "sources": [
            {
                "source_id": "synthetic-demo",
                "snapshot_id": "synthetic-snapshot-1",
                "sha256": hashlib.sha256(
                    (FIXTURES / "source-snapshot.synthetic.json").read_bytes()
                ).hexdigest(),
                "url": None,
                "retrieved_at": "2024-01-16T00:00:00Z",
                "license": "generated fixture",
            }
        ],
        "fundamental_section": {
            "status": "complete",
            "findings": [
                {
                    "kind": "fact",
                    "text": "Synthetic revenue input equals zero.",
                    "observation_indexes": [0],
                    "method": None,
                }
            ],
            "reason": None,
        },
        "technical_section": {"status": "blocked", "findings": [], "reason": "No prices"},
        "synthesis_section": {
            "status": "blocked",
            "findings": [],
            "reason": "No research synthesis implemented",
        },
        "scenario_section": {
            "status": "not_applicable",
            "findings": [],
            "reason": "Envelope fixture only",
        },
        "uncertainties": ["No external source was verified"],
        "limitations": ["Synthetic fixture; not investment evidence"],
        "disclaimer": DISCLAIMER,
        "model_provenance": None,
        "prompt_template_version": None,
        "chart_artifact_ids": [],
    }


def test_sealed_sample_is_reproducible_and_schema_valid() -> None:
    sealed = seal_report(ReportContent.model_validate(valid_content()))
    payload = sealed.model_dump(mode="json")
    sample = json.loads((FIXTURES / "report.synthetic.json").read_text("utf-8"))
    assert payload == sample
    schema = json.loads((ROOT / "contracts/v1/report.schema.json").read_text("utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
    assert ReportRevision.model_validate_json(json.dumps(sample)) == sealed
    assert sealed.status == "partial"
    assert sealed.input.data_origin == "synthetic"


def test_hash_ignores_object_key_order_but_not_data() -> None:
    content = valid_content()
    first = seal_report(ReportContent.model_validate(content))
    reverse = dict(reversed(list(content.items())))
    assert seal_report(ReportContent.model_validate(reverse)).checksum == first.checksum
    content["input"]["observations"][0]["value"] = 1
    second = seal_report(ReportContent.model_validate(content))
    assert second.input_sha256 != first.input_sha256
    assert second.checksum != first.checksum


def test_hash_uses_normalized_instants() -> None:
    content = valid_content()
    first = seal_report(ReportContent.model_validate(content))
    content["generated_at_utc"] = "2024-02-02T01:00:00+01:00"
    assert seal_report(ReportContent.model_validate(content)).checksum == first.checksum


@pytest.mark.parametrize("field", ["checksum", "input_sha256"])
def test_tampered_checksums_are_rejected(field: str) -> None:
    payload = seal_report(ReportContent.model_validate(valid_content())).model_dump(mode="json")
    payload[field] = "0" * 64
    with pytest.raises(ValidationError, match="checksum mismatch"):
        ReportRevision.model_validate(payload)


def test_checksum_rejects_text_tampering() -> None:
    payload = seal_report(ReportContent.model_validate(valid_content())).model_dump(mode="json")
    payload["limitations"] = ["Altered after sealing"]
    with pytest.raises(ValidationError, match="report checksum mismatch"):
        ReportRevision.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pipeline_git_sha", "shortsha"),
        ("revision", True),
        ("revision", 0),
        ("chart_artifact_ids", ["unverified-chart"]),
        ("model_provenance", {"provider": "paid"}),
        ("limitations", []),
        ("disclaimer", "Buy now"),
        ("report_id", "../private.json"),
    ],
)
def test_invalid_report_metadata(field: str, value: Any) -> None:
    payload = valid_content()
    payload[field] = value
    with pytest.raises(ValidationError):
        ReportContent.model_validate(payload)


def test_generation_cannot_precede_cutoff() -> None:
    payload = valid_content()
    payload["generated_at_utc"] = "2024-01-31T00:00:00Z"
    with pytest.raises(ValidationError):
        ReportContent.model_validate(payload)


@pytest.mark.parametrize("revision", [1, 2])
def test_revision_parent_rules(revision: int) -> None:
    payload = valid_content()
    payload["revision"] = revision
    if revision == 1:
        payload["parent_revision_id"] = "a16aef32-a350-4a21-9163-af71ee30a3fa"
    with pytest.raises(ValidationError):
        ReportContent.model_validate(payload)


def test_next_revision_requires_new_id_and_resealing() -> None:
    first = seal_report(ReportContent.model_validate(valid_content()))
    payload = valid_content()
    payload.update(revision=2, parent_revision_id=str(first.revision_id))
    with pytest.raises(ValidationError):
        ReportContent.model_validate(payload)
    payload["revision_id"] = "9dffb3e7-a7f5-4dd6-8323-33d7b8664818"
    second = seal_report(ReportContent.model_validate(payload))
    assert second.report_id == first.report_id
    assert second.checksum != first.checksum


@pytest.mark.parametrize("case", ["missing", "duplicate", "extra", "early", "late", "live_no_url"])
def test_provenance_must_match_available_observations(case: str) -> None:
    payload = valid_content()
    if case == "missing":
        payload["sources"] = []
    elif case == "duplicate":
        payload["sources"].append(deepcopy(payload["sources"][0]))
    elif case == "extra":
        extra = deepcopy(payload["sources"][0])
        extra["snapshot_id"] = "unrelated"
        payload["sources"].append(extra)
    elif case == "early":
        payload["sources"][0]["retrieved_at"] = "2024-01-15T00:00:00Z"
    elif case == "late":
        payload["sources"][0]["retrieved_at"] = "2024-02-03T00:00:00Z"
    else:
        payload["input"]["data_origin"] = "live"
    with pytest.raises(ValidationError):
        ReportContent.model_validate(payload)


@pytest.mark.parametrize("indexes", [[], [1], [2], [-1], [True], [0, 0]])
def test_finding_requires_existing_available_evidence(indexes: list[Any]) -> None:
    payload = valid_content()
    payload["fundamental_section"]["findings"][0]["observation_indexes"] = indexes
    with pytest.raises(ValidationError):
        ReportContent.model_validate(payload)


def test_calculation_requires_method_and_evidence() -> None:
    payload = valid_content()
    finding = payload["fundamental_section"]["findings"][0]
    finding["kind"] = "calculation"
    with pytest.raises(ValidationError):
        ReportContent.model_validate(payload)
    finding["method"] = "identity-fixture-1"
    assert ReportContent.model_validate(payload).fundamental_section.findings[0].method


@pytest.mark.parametrize("status", ["complete", "partial", "blocked", "failed", "not_applicable"])
def test_section_status_cannot_hide_missing_content(status: str) -> None:
    payload = valid_content()
    section = payload["technical_section"]
    section["status"] = status
    section["reason"] = None
    with pytest.raises(ValidationError):
        ReportContent.model_validate(payload)


def test_partial_data_cannot_be_promoted_to_complete() -> None:
    payload = valid_content()
    payload["status"] = "complete"
    with pytest.raises(ValidationError):
        ReportContent.model_validate(payload)


def test_failed_section_requires_failed_report_but_preserves_other_findings() -> None:
    payload = valid_content()
    payload["technical_section"]["status"] = "failed"
    with pytest.raises(ValidationError):
        ReportContent.model_validate(payload)
    payload["status"] = "failed"
    result = seal_report(ReportContent.model_validate(payload))
    assert result.fundamental_section.findings


def test_absence_only_report_is_blocked_without_inventing_sources() -> None:
    payload = valid_content()
    payload["input"]["observations"] = [payload["input"]["observations"][1]]
    payload["sources"] = []
    payload["fundamental_section"] = {
        "status": "blocked",
        "findings": [],
        "reason": "Missing inputs",
    }
    payload["status"] = "blocked"
    result = seal_report(ReportContent.model_validate(payload))
    assert result.sources == []
    assert result.input.observations[0].value is None


def test_sealing_revalidates_mutated_nested_model() -> None:
    model = ReportContent.model_validate(valid_content())
    model.input.observations[0].period_end = model.generated_at_utc
    with pytest.raises(ValidationError):
        seal_report(model)


def test_unknown_fields_and_non_finite_values_cannot_be_sealed() -> None:
    payload = valid_content()
    payload["execute"] = "arbitrary code"
    with pytest.raises(ValidationError):
        ReportContent.model_validate(payload)
    with pytest.raises(ValueError):
        canonical_sha256({"value": float("nan")})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("report_id", "f8550d24520042feb715a564af5c8c42"),
        ("report_id", "urn:uuid:f8550d24-5200-42fe-b715-a564af5c8c42"),
        ("url", "ftp://example.invalid/snapshot"),
        ("url", "http:example.invalid/snapshot"),
        ("url", "https://example.invalid/snapshot "),
    ],
)
def test_url_and_uuid_shape_agree_at_both_boundaries(field: str, value: str) -> None:
    sealed = seal_report(ReportContent.model_validate(valid_content())).model_dump(mode="json")
    if field == "url":
        sealed["sources"][0][field] = value
    else:
        sealed[field] = value
    schema = json.loads((ROOT / "contracts/v1/report.schema.json").read_text("utf-8"))
    assert list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(sealed))
    with pytest.raises(ValidationError):
        ReportRevision.model_validate(sealed)


def test_complete_requires_available_data_and_productive_sections() -> None:
    payload = valid_content()
    payload["input"]["observations"].pop()
    for key in ["technical_section", "synthesis_section", "scenario_section"]:
        payload[key] = {"status": "not_applicable", "findings": [], "reason": "Fixture scope"}
    payload["status"] = "complete"
    assert seal_report(ReportContent.model_validate(payload)).status == "complete"
    payload["fundamental_section"] = deepcopy(payload["scenario_section"])
    with pytest.raises(ValidationError):
        ReportContent.model_validate(payload)
    payload["status"] = "blocked"
    assert seal_report(ReportContent.model_validate(payload)).status == "blocked"

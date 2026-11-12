"""Portable export validates identity, evidence, deterministic sealing and selected AI."""

from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_ai_history_context import context_fixture, narrative

from alphasense.ai_analysis_contracts import AiAnalysisRecord, AiNarrative
from alphasense.ai_history_contracts import AiHistoryNarrative
from alphasense.financial_history import FinancialHistory
from alphasense.financial_ratios import build_financial_ratios
from alphasense.research_export import ResearchExport, build_research_export


def export_fixture(version=None):
    report, history, context = context_fixture()
    ratios = build_financial_ratios(history)
    if version is None:
        return report, ratios, None
    content = {
        "request_id": uuid4(),
        "report_id": report.report_id,
        "revision": report.revision,
        "report_checksum": report.checksum,
        "status": "completed",
        "created_at": report.input.as_of,
        "finished_at": report.input.as_of + timedelta(seconds=1),
        "model_id": "saved-synthetic-model",
        "error_code": None,
    }
    if version == "v1":
        content.update(
            analysis=AiNarrative(
                summary=[{"text": "Zapisane dane przychodów.", "observation_indexes": [0]}],
                strengths=[],
                risks=[],
                questions=[],
                limitations=["Ograniczone dane."],
            )
        )
    else:
        content.update(
            prompt_version="report-history-v2",
            evidence_context=context,
            analysis=AiHistoryNarrative.model_validate(narrative()),
        )
    return report, ratios, AiAnalysisRecord.model_validate(content)


@pytest.mark.parametrize("version", [None, "v1", "v2"])
def test_sealed_repeat_export_preserves_exact_inputs(version):
    report, ratios, ai = export_fixture(version)
    first = build_research_export(report, ratios, ai)
    assert first == build_research_export(report, ratios, ai)
    assert ResearchExport.model_validate_json(first.model_dump_json()) == first
    assert first.report == report and first.financial_ratios == ratios and first.ai_analysis == ai
    if version == "v1":
        assert "evidence_context" not in first.model_dump(mode="json")["ai_analysis"]
    if version == "v2":
        assert (
            first.ai_analysis.evidence_context.context_sha256 == ai.evidence_context.context_sha256
        )


def test_resealed_changed_report_identity_refused():
    report, ratios, _ = export_fixture()
    changed = ratios.model_copy(update={"report_id": uuid4()})
    with pytest.raises((ValidationError, ValueError)):
        build_research_export(report, changed)


@pytest.mark.parametrize("field", ["checksum", "limitations"])
def test_tampering_fails_without_new_checksum(field):
    report, ratios, _ = export_fixture()
    raw = build_research_export(report, ratios).model_dump(mode="json")
    raw[field] = "0" * 64 if field == "checksum" else ["Changed after download."]
    with pytest.raises(ValidationError, match="Export checksum mismatch"):
        ResearchExport.model_validate(raw)


@pytest.mark.parametrize("field", ["source_sha256", "source_snapshot_id", "source_url"])
def test_forged_history_provenance_rejected(field):
    report, ratios, _ = export_fixture()
    history = ratios.history.model_dump(mode="json")
    history["series"][0][field] = {
        "source_sha256": "0" * 64,
        "source_snapshot_id": str(uuid4()),
        "source_url": "https://data.sec.gov/changed",
    }[field]
    forged = build_financial_ratios(FinancialHistory.model_validate(history))
    with pytest.raises((ValidationError, ValueError), match="Export history source mismatch"):
        build_research_export(report, forged)


def test_changed_latest_value_cannot_be_resealed_with_valid_ratio_arithmetic():
    report, ratios, _ = export_fixture()
    history = ratios.history.model_dump(mode="json")
    history["series"][0]["points"][-1]["value"] = "999"
    forged = build_financial_ratios(FinancialHistory.model_validate(history))
    with pytest.raises(
        (ValidationError, ValueError), match="Export history current value mismatch"
    ):
        build_research_export(report, forged)


@pytest.mark.parametrize("status", ["running", "failed"])
def test_noncompleted_ai_is_not_exported(status):
    report, ratios, ai = export_fixture("v1")
    raw = ai.model_dump(mode="python")
    raw.update(
        status=status,
        analysis=None,
        finished_at=None if status == "running" else ai.finished_at,
        error_code=None if status == "running" else "MODEL_ERROR",
    )
    with pytest.raises((ValidationError, ValueError), match="EXPORT_AI_NOT_COMPLETED"):
        build_research_export(report, ratios, AiAnalysisRecord.model_validate(raw))


def test_ai_from_other_report_is_never_silently_used():
    report, ratios, ai = export_fixture("v1")
    ai = ai.model_copy(update={"report_id": uuid4()})
    with pytest.raises((ValidationError, ValueError), match="EXPORT_AI_MISMATCH"):
        build_research_export(report, ratios, ai)


@pytest.mark.parametrize("index", [1, 999])
def test_legacy_claims_cannot_cite_missing_or_unknown_observations(index):
    report, ratios, ai = export_fixture("v1")
    raw = ai.model_dump(mode="json")
    raw["analysis"]["summary"][0]["observation_indexes"] = [index]
    with pytest.raises((ValidationError, ValueError), match="legacy AI evidence mismatch"):
        build_research_export(report, ratios, AiAnalysisRecord.model_validate(raw))

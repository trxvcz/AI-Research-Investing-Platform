"""Deterministic research bundle, bound to one report and an explicitly selected AI result."""

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from alphasense.ai_analysis_contracts import AiAnalysisRecord, AiNarrative
from alphasense.ai_history_context import validate_history_context, validate_history_narrative
from alphasense.contracts import Contract
from alphasense.financial_ratios import FinancialRatios
from alphasense.report_contracts import ReportRevision, Sha256, canonical_sha256

ExportText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2000)]


class ResearchExportInvalid(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ResearchExport(Contract):
    export_version: Literal["research-export-v1"] = "research-export-v1"
    report: ReportRevision
    ai_analysis: AiAnalysisRecord | None
    financial_ratios: FinancialRatios
    limitations: Annotated[list[ExportText], Field(min_length=1, max_length=8)]
    checksum: Sha256

    @model_validator(mode="after")
    def integrity(self) -> Self:
        report = self.report
        ratios = self.financial_ratios
        identity = (report.report_id, report.revision, report.checksum)
        if (ratios.report_id, ratios.revision, ratios.report_checksum) != identity:
            raise ValueError("Export ratio identity mismatch")
        if ratios.as_of != report.input.as_of:
            raise ValueError("Export history availability mismatch")
        sources = {source.snapshot_id: source for source in report.sources}
        for series in ratios.history.series:
            source = sources.get(str(series.source_snapshot_id))
            if source is None or (source.sha256, str(source.url), source.retrieved_at) != (
                series.source_sha256,
                series.source_url,
                series.available_at,
            ):
                raise ValueError("Export history source mismatch")
            anchors = [
                o
                for o in report.input.observations
                if o.status == "available"
                and o.metric == series.metric
                and o.snapshot_id == str(series.source_snapshot_id)
                and o.unit == "currency"
                and o.currency == series.currency
            ]
            if not anchors:
                raise ValueError("Export history observation missing")
            anchor = max(anchors, key=lambda o: o.period_end)
            if series.points:
                latest = max(series.points, key=lambda point: point.period_end)
                if (latest.period_start, latest.period_end, Decimal(latest.value)) != (
                    anchor.period_start.date(),
                    anchor.period_end.date(),
                    Decimal(str(anchor.value)),
                ):
                    raise ValueError("Export history current value mismatch")

        ai = self.ai_analysis
        if ai is not None:
            if (ai.report_id, ai.revision, ai.report_checksum) != identity:
                raise ResearchExportInvalid("EXPORT_AI_MISMATCH")
            if ai.status != "completed" or ai.analysis is None:
                raise ResearchExportInvalid("EXPORT_AI_NOT_COMPLETED")
            if isinstance(ai.analysis, AiNarrative):
                claims = [
                    *ai.analysis.summary,
                    *ai.analysis.strengths,
                    *ai.analysis.risks,
                    *ai.analysis.questions,
                ]
                if any(
                    index >= len(report.input.observations)
                    or report.input.observations[index].status != "available"
                    for claim in claims
                    for index in claim.observation_indexes
                ):
                    raise ValueError("Export legacy AI evidence mismatch")
            elif ai.evidence_context is not None:
                context = validate_history_context(ai.evidence_context, report)
                validate_history_narrative(context, ai.analysis.model_dump_json())
            else:
                raise ValueError("Export history AI context missing")
        if self.checksum != canonical_sha256(self.model_dump(mode="json", exclude={"checksum"})):
            raise ValueError("Export checksum mismatch")
        return self


def build_research_export(
    report: ReportRevision, ratios: FinancialRatios, ai: AiAnalysisRecord | None = None
) -> ResearchExport:
    """Revalidate mutable instances; never create or infer a model response."""
    payload = {
        "export_version": "research-export-v1",
        "report": ReportRevision.model_validate(report.model_dump(mode="python")).model_dump(
            mode="json"
        ),
        "ai_analysis": None
        if ai is None
        else AiAnalysisRecord.model_validate(ai.model_dump(mode="python")).model_dump(mode="json"),
        "financial_ratios": FinancialRatios.model_validate(
            ratios.model_dump(mode="python")
        ).model_dump(mode="json"),
        "limitations": [
            "Eksport zawiera zapisane wyniki, nie nową analizę AI. "
            "To research, bez rekomendacji i składania zleceń.",
            "Porównawcze dane sprawozdawcze mogą zawierać przekształcenia. "
            "Nie odtwarzają wiedzy inwestora w dawnym roku.",
            "Dokument można czytać bez aplikacji. Otwarcie źródeł SEC wymaga sieci. "
            "Suma kontrolna wykrywa zmianę treści, nie potwierdza autentyczności.",
        ],
    }
    return ResearchExport.model_validate({**payload, "checksum": canonical_sha256(payload)})

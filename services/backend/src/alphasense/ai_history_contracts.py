"""Frozen evidence and typed claims for report-history-v2; independent of v1."""

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from alphasense.contracts import Contract, Currency, Metric, Timestamp, Unit
from alphasense.financial_history import DecimalString, PercentString
from alphasense.report_contracts import ReportUUID, Sha256, SourceProvenance, canonical_sha256

Index = Annotated[int, Field(strict=True, ge=0, le=63)]
Text = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1200)]


class AiHistoryFact(Contract):
    kind: Literal["fact"] = "fact"
    index: Index
    metric: Metric
    unit: Unit
    currency: Currency | None
    value: DecimalString
    period_start: Timestamp
    period_end: Timestamp
    available_at: Timestamp
    source: SourceProvenance
    report_observation_index: Annotated[int, Field(strict=True, ge=0, le=999)] | None
    filing_accession: (
        Annotated[str, StringConstraints(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")] | None
    )

    @model_validator(mode="after")
    def chronology(self) -> Self:
        if not self.period_start <= self.period_end <= self.available_at:
            raise ValueError("Invalid evidence chronology")
        if self.available_at != self.source.retrieved_at:
            raise ValueError("Invalid source availability")
        return self


class AiHistoryComparison(Contract):
    kind: Literal["comparison"] = "comparison"
    index: Index
    metric: Metric
    previous_index: Index
    current_index: Index
    delta_value: DecimalString | None
    delta_percent: PercentString | None
    comparison_reason: Literal["NON_POSITIVE_BASE", "PERIODS_NOT_COMPARABLE"] | None


Evidence = Annotated[AiHistoryFact | AiHistoryComparison, Field(discriminator="kind")]


class AiHistoryContext(Contract):
    context_version: Literal["report-history-context-v1"] = "report-history-context-v1"
    report_id: ReportUUID
    revision: Annotated[int, Field(strict=True, ge=1)]
    report_checksum: Sha256
    as_of: Timestamp
    methodology_version: Literal["sec-comparatives-v1"] = "sec-comparatives-v1"
    evidence: Annotated[list[Evidence], Field(min_length=1, max_length=64)]
    limitations: Annotated[list[Text], Field(min_length=1, max_length=16)]
    context_sha256: Sha256

    @model_validator(mode="after")
    def integrity(self) -> Self:
        from alphasense.ai_history_context import _validate_internal

        if self.context_sha256 != canonical_sha256(
            self.model_dump(mode="json", exclude={"context_sha256"})
        ):
            raise ValueError("Context hash mismatch")
        _validate_internal(self)
        return self


class AiHistoryClaim(Contract):
    kind: Literal["state", "trend", "question"]
    text: Text
    evidence_indexes: Annotated[list[Index], Field(min_length=1, max_length=20)]
    direction: Literal["increase", "decrease", "unchanged"] | None

    @model_validator(mode="after")
    def references(self) -> Self:
        if len(set(self.evidence_indexes)) != len(self.evidence_indexes):
            raise ValueError("Duplicate evidence reference")
        if self.kind == "trend":
            if len(self.evidence_indexes) != 1 or self.direction is None:
                raise ValueError("Trend requires one comparison and direction")
        elif self.direction is not None:
            raise ValueError("Only trends have direction")
        return self


class AiHistoryNarrative(Contract):
    summary: Annotated[list[AiHistoryClaim], Field(min_length=1, max_length=6)]
    strengths: Annotated[list[AiHistoryClaim], Field(max_length=6)]
    risks: Annotated[list[AiHistoryClaim], Field(max_length=6)]
    questions: Annotated[list[AiHistoryClaim], Field(max_length=6)]
    limitations: Annotated[list[Text], Field(min_length=1, max_length=12)]

    @model_validator(mode="after")
    def sections(self) -> Self:
        if any(c.kind == "question" for c in self.summary + self.strengths + self.risks):
            raise ValueError("Questions must be in their own section")
        if any(c.kind != "question" for c in self.questions):
            raise ValueError("Question section requires question claims")
        return self

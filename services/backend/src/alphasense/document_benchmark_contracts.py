"""Offline quality evaluation contracts; saved drafts never prove a model invocation."""

from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from alphasense.contracts import Contract, Currency, Identifier, Metric, Timestamp
from alphasense.document_contracts import (
    CalendarDate,
    DecimalText,
    NumberLocale,
    ReaderVersion,
    validate_reader_options,
)
from alphasense.provider_contracts import DataClassification
from alphasense.report_contracts import Sha256

DataOrigin = Literal["synthetic", "user_supplied"]
Count = Annotated[int, Field(strict=True, ge=0)]


class GoldFact(Contract):
    metric: Metric
    value: DecimalText
    currency: Currency
    period_start: CalendarDate
    period_end: CalendarDate
    scope: Literal["consolidated", "separate"]

    @model_validator(mode="after")
    def ordered_period(self) -> Self:
        if self.period_start > self.period_end:
            raise ValueError("Invalid gold period")
        return self


def fact_key(fact: GoldFact) -> tuple[object, ...]:
    return (
        fact.metric,
        Decimal(fact.value),
        fact.currency,
        fact.period_start,
        fact.period_end,
        fact.scope,
    )


class BenchmarkCase(Contract):
    case_id: Identifier
    issuer_label: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)]
    format: Literal["text", "html", "xlsx", "pdf"]
    reader_version: ReaderVersion | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    number_locale: NumberLocale | None = Field(default=None, exclude_if=lambda value: value is None)
    classification: DataClassification
    data_origin: DataOrigin
    content_base64: Annotated[str, StringConstraints(strict=True, min_length=4, max_length=1398104)]
    document_sha256: Sha256
    source_available_at: Timestamp
    as_of: Timestamp
    expected_facts: Annotated[list[GoldFact], Field(max_length=64)]

    @model_validator(mode="after")
    def valid_gold(self) -> Self:
        validate_reader_options(self.format, self.reader_version, self.number_locale)
        if self.source_available_at > self.as_of:
            raise ValueError("Source unavailable as of evaluation")
        keys = [fact_key(fact) for fact in self.expected_facts]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate gold fact")
        return self


class BenchmarkSuite(Contract):
    schema_version: Literal["1.0"]
    suite_id: Identifier
    cases: Annotated[list[BenchmarkCase], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def unique_cases(self) -> Self:
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("Duplicate benchmark case")
        return self


class BenchmarkResponse(Contract):
    case_id: Identifier
    document_sha256: Sha256
    raw_json: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=262144)]


class BenchmarkResponses(Contract):
    schema_version: Literal["1.0"]
    suite_sha256: Sha256
    response_origin: Literal["hand_authored_reference", "saved_unverified_response"]
    cases: Annotated[list[BenchmarkResponse], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def unique_cases(self) -> Self:
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("Duplicate benchmark response")
        return self


class BenchmarkRatio(Contract):
    numerator: Count
    denominator: Count
    value: Annotated[str, StringConstraints(pattern=r"^(0\.[0-9]{6}|1\.000000)$")] | None

    @model_validator(mode="after")
    def consistent_ratio(self) -> Self:
        if self.numerator > self.denominator:
            raise ValueError("Invalid ratio")
        with localcontext() as context:
            context.prec = 64
            expected = (
                format(
                    (Decimal(self.numerator) / Decimal(self.denominator)).quantize(
                        Decimal("0.000001"), rounding=ROUND_HALF_EVEN
                    ),
                    ".6f",
                )
                if self.denominator
                else None
            )
        if self.value != expected:
            raise ValueError("Inconsistent ratio")
        return self


class BenchmarkCaseResult(Contract):
    case_id: Identifier
    data_origin: DataOrigin
    true_positives: Count
    false_positives: Count
    false_negatives: Count
    evidence_rejections: Count
    invalid_response: Annotated[bool, Field(strict=True)]
    expected_abstention: Annotated[bool, Field(strict=True)]
    successful_abstention: Annotated[bool, Field(strict=True)]

    @model_validator(mode="after")
    def consistent_outcome(self) -> Self:
        if self.evidence_rejections > self.false_positives:
            raise ValueError("Invalid rejection count")
        if self.expected_abstention and (self.true_positives or self.false_negatives):
            raise ValueError("Invalid abstention gold")
        if self.invalid_response and self.true_positives:
            raise ValueError("Invalid response cannot match gold")
        expected = (
            self.expected_abstention and not self.invalid_response and not self.false_positives
        )
        if self.successful_abstention != expected:
            raise ValueError("Invalid abstention result")
        return self


class BenchmarkResult(Contract):
    schema_version: Literal["1.0"] = "1.0"
    scorer_version: Literal["document-offline-v1"] = "document-offline-v1"
    suite_sha256: Sha256
    responses_sha256: Sha256
    response_origin: Literal["hand_authored_reference", "saved_unverified_response"]
    qualification_status: Literal["not_qualified_offline"] = "not_qualified_offline"
    cases: Annotated[list[BenchmarkCaseResult], Field(min_length=1, max_length=32)]
    true_positives: Count
    false_positives: Count
    false_negatives: Count
    evidence_rejections: Count
    invalid_responses: Count
    expected_abstentions: Count
    successful_abstentions: Count
    precision: BenchmarkRatio
    recall: BenchmarkRatio

    @model_validator(mode="after")
    def consistent_aggregates(self) -> Self:
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("Duplicate benchmark outcome")
        for name in ("true_positives", "false_positives", "false_negatives", "evidence_rejections"):
            if getattr(self, name) != sum(getattr(case, name) for case in self.cases):
                raise ValueError("Inconsistent benchmark total")
        for aggregate, field in (
            ("invalid_responses", "invalid_response"),
            ("expected_abstentions", "expected_abstention"),
            ("successful_abstentions", "successful_abstention"),
        ):
            if getattr(self, aggregate) != sum(getattr(case, field) for case in self.cases):
                raise ValueError("Inconsistent benchmark total")
        if (
            self.precision.numerator != self.true_positives
            or self.precision.denominator != self.true_positives + self.false_positives
            or self.recall.numerator != self.true_positives
            or self.recall.denominator != self.true_positives + self.false_negatives
        ):
            raise ValueError("Inconsistent benchmark ratio")
        return self

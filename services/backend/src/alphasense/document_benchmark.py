"""Deterministic offline scoring of frozen documents and saved extraction drafts."""

import base64
import hashlib
import json
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from uuid import NAMESPACE_URL, uuid5

from alphasense.contracts import Contract
from alphasense.document_agent import validate_draft
from alphasense.document_benchmark_contracts import (
    BenchmarkCaseResult,
    BenchmarkRatio,
    BenchmarkResponses,
    BenchmarkResult,
    BenchmarkSuite,
    fact_key,
)
from alphasense.document_contracts import CandidateFact
from alphasense.document_readers import read_text_document

MAX_RAW_BYTES = 1024 * 1024
MAX_SUITE_RAW_BYTES = 8 * 1024 * 1024
MAX_DRAFT_BYTES = 256 * 1024


class BenchmarkInvalid(ValueError):
    """A stable refusal which never includes a source or parser diagnostic."""


def canonical_hash(model: Contract) -> str:
    """Hash the revalidated canonical contract, including frozen gold annotations."""
    try:
        if not isinstance(model, Contract):
            raise ValueError("Contract required")
        checked = type(model).model_validate(model.model_dump(mode="python", warnings=False))
        raw = json.dumps(
            checked.model_dump(mode="json", warnings=False),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()
    except (ValueError, TypeError, UnicodeError, RecursionError, AttributeError, OverflowError):
        raise BenchmarkInvalid("DOCUMENT_BENCHMARK_INVALID") from None


def _ratio(numerator: int, denominator: int) -> BenchmarkRatio:
    value = None
    if denominator:
        with localcontext() as context:
            context.prec = 32
            value = format(
                (Decimal(numerator) / Decimal(denominator)).quantize(
                    Decimal("0.000001"), rounding=ROUND_HALF_EVEN
                ),
                "f",
            )
    return BenchmarkRatio(numerator=numerator, denominator=denominator, value=value)


def _candidate_key(fact: CandidateFact) -> tuple[object, ...]:
    return (
        fact.metric,
        Decimal(fact.value),
        fact.currency,
        fact.period_start,
        fact.period_end,
        fact.scope,
    )


def evaluate(suite: BenchmarkSuite, responses: BenchmarkResponses) -> BenchmarkResult:
    """Score every frozen case without tools, providers, model inference or publication."""
    try:
        if not isinstance(suite, BenchmarkSuite) or not isinstance(responses, BenchmarkResponses):
            raise ValueError("Benchmark contracts required")
        # model_copy and nested mutation bypass Pydantic validation. Rebuild from
        # dictionaries at the execution boundary, suppressing diagnostic values.
        suite = BenchmarkSuite.model_validate(suite.model_dump(mode="python", warnings=False))
        responses = BenchmarkResponses.model_validate(
            responses.model_dump(mode="python", warnings=False)
        )
        suite_hash = canonical_hash(suite)
        if suite_hash != responses.suite_sha256:
            raise ValueError("Suite identity mismatch")
        saved = {response.case_id: response for response in responses.cases}
        if set(saved) != {case.case_id for case in suite.cases}:
            raise ValueError("Case coverage mismatch")

        sources: list[bytes] = []
        total_raw = 0
        # Establish identity and the whole-suite byte limit before parsing a PDF
        # or allowing any single successful case to contribute to the score.
        for case in suite.cases:
            response = saved[case.case_id]
            if response.document_sha256 != case.document_sha256:
                raise ValueError("Response document mismatch")
            if len(response.raw_json.encode("utf-8")) > MAX_DRAFT_BYTES:
                raise ValueError("Draft byte limit")
            raw = base64.b64decode(case.content_base64, validate=True)
            total_raw += len(raw)
            if (
                not 1 <= len(raw) <= MAX_RAW_BYTES
                or total_raw > MAX_SUITE_RAW_BYTES
                or base64.b64encode(raw).decode("ascii") != case.content_base64
                or hashlib.sha256(raw).hexdigest() != case.document_sha256
            ):
                raise ValueError("Invalid frozen document")
            sources.append(raw)

        outcomes: list[BenchmarkCaseResult] = []
        for case, raw in zip(suite.cases, sources, strict=True):
            packet = read_text_document(
                raw,
                document_id=uuid5(
                    NAMESPACE_URL, "document-benchmark:" + suite_hash + ":" + case.case_id
                ),
                classification=case.classification,
                format=case.format,
                reader_version=case.reader_version,
                number_locale=case.number_locale,
            )
            result = validate_draft(packet, saved[case.case_id].raw_json, "offline-benchmark")
            remaining = {fact_key(fact) for fact in case.expected_facts}
            true_positives = false_positives = evidence_rejections = 0
            for review in result.facts:
                key = _candidate_key(review.fact)
                if review.status == "needs_review" and key in remaining:
                    true_positives += 1
                    remaining.remove(key)
                else:
                    false_positives += 1
                if review.status == "rejected":
                    evidence_rejections += 1
            invalid = result.error_code == "DRAFT_INVALID"
            abstention = not case.expected_facts
            outcomes.append(
                BenchmarkCaseResult(
                    case_id=case.case_id,
                    data_origin=case.data_origin,
                    true_positives=true_positives,
                    false_positives=false_positives,
                    false_negatives=len(remaining),
                    evidence_rejections=evidence_rejections,
                    invalid_response=invalid,
                    expected_abstention=abstention,
                    successful_abstention=abstention and not invalid and not result.facts,
                )
            )

        tp = sum(case.true_positives for case in outcomes)
        fp = sum(case.false_positives for case in outcomes)
        fn = sum(case.false_negatives for case in outcomes)
        return BenchmarkResult(
            suite_sha256=suite_hash,
            responses_sha256=canonical_hash(responses),
            response_origin=responses.response_origin,
            cases=outcomes,
            true_positives=tp,
            false_positives=fp,
            false_negatives=fn,
            evidence_rejections=sum(case.evidence_rejections for case in outcomes),
            invalid_responses=sum(case.invalid_response for case in outcomes),
            expected_abstentions=sum(case.expected_abstention for case in outcomes),
            successful_abstentions=sum(case.successful_abstention for case in outcomes),
            precision=_ratio(tp, tp + fp),
            recall=_ratio(tp, tp + fn),
        )
    except (ValueError, TypeError, UnicodeError, RecursionError, AttributeError, OverflowError):
        raise BenchmarkInvalid("DOCUMENT_BENCHMARK_INVALID") from None

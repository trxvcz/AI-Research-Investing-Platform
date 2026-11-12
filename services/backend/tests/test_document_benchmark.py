"""Offline semantic scoring rejects plausible but incorrect financial interpretations."""

import base64
import hashlib
import json
from copy import deepcopy
from unittest.mock import Mock

import pytest

from alphasense import document_benchmark
from alphasense.document_benchmark import BenchmarkInvalid, canonical_hash, evaluate
from alphasense.document_benchmark_contracts import (
    BenchmarkCase,
    BenchmarkResponse,
    BenchmarkResponses,
    BenchmarkSuite,
    GoldFact,
)

RAW = b"Consolidated revenue for 2025: 12.5 million PLN."


def gold(**updates):
    value = {
        "metric": "revenue",
        "value": "12500000",
        "currency": "PLN",
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "scope": "consolidated",
    }
    return GoldFact.model_validate(value | updates)


def case(raw=RAW, *, case_id="issuer-a-2025", facts=None, **updates):
    value = {
        "case_id": case_id,
        "issuer_label": "Synthetic issuer A",
        "format": "text",
        "classification": "private",
        "data_origin": "synthetic",
        "content_base64": base64.b64encode(raw).decode("ascii"),
        "document_sha256": hashlib.sha256(raw).hexdigest(),
        "source_available_at": "2026-01-01T00:00:00Z",
        "as_of": "2026-01-02T00:00:00Z",
        "expected_facts": [gold()] if facts is None else facts,
    }
    return BenchmarkCase.model_validate(value | updates)


def suite(*cases):
    return BenchmarkSuite(schema_version="1.0", suite_id="synthetic-offline-v1", cases=list(cases))


def fact(**updates):
    return {
        "metric": "revenue",
        "value_token": "12.5",
        "value": "12500000",
        "scale": 1000000,
        "currency": "PLN",
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "scope": "consolidated",
        "evidence": [{"block_id": "block-1", "quote": "12.5 million PLN"}],
    } | updates


def draft(*facts):
    return json.dumps({"schema_version": "1.0", "facts": list(facts)})


def responses(frozen, *drafts):
    return BenchmarkResponses(
        schema_version="1.0",
        suite_sha256=canonical_hash(frozen),
        response_origin="hand_authored_reference",
        cases=[
            BenchmarkResponse(
                case_id=entry.case_id,
                document_sha256=entry.document_sha256,
                raw_json=raw,
            )
            for entry, raw in zip(frozen.cases, drafts, strict=True)
        ],
    )


def test_correct_semantics_and_citation_count_once_without_qualifying_a_model():
    frozen = suite(case())
    saved = responses(frozen, draft(fact()))
    result = evaluate(frozen, saved)
    assert (result.true_positives, result.false_positives, result.false_negatives) == (1, 0, 0)
    assert result.precision.value == result.recall.value == "1.000000"
    assert result.evidence_rejections == result.invalid_responses == 0
    assert result.qualification_status == "not_qualified_offline"
    assert result.response_origin == "hand_authored_reference"
    assert result.responses_sha256 == canonical_hash(saved)
    assert result == evaluate(frozen, saved)


@pytest.mark.parametrize(
    "updates",
    [
        {"currency": "USD"},
        {"metric": "net_income"},
        {"period_start": "2024-01-01"},
        {"period_end": "2026-12-31"},
        {"scope": "separate"},
        {"scope": "unknown"},
    ],
)
def test_lexically_valid_but_semantically_wrong_fact_is_a_false_positive(updates):
    frozen = suite(case())
    result = evaluate(frozen, responses(frozen, draft(fact(**updates))))
    assert (result.true_positives, result.false_positives, result.false_negatives) == (0, 1, 1)
    assert result.precision.value == result.recall.value == "0.000000"
    assert result.evidence_rejections == 0
    assert result.invalid_responses == 0


@pytest.mark.parametrize(
    "updates",
    [
        {"value": "12500001"},
        {"scale": 1000, "value": "12500"},
        {"evidence": [{"block_id": "block-1", "quote": "not in the document"}]},
        {"evidence": [{"block_id": "missing-block", "quote": "12.5 million PLN"}]},
    ],
)
def test_uncited_or_arithmetically_wrong_value_never_matches_gold(updates):
    frozen = suite(case())
    result = evaluate(frozen, responses(frozen, draft(fact(**updates))))
    assert (result.true_positives, result.false_positives, result.false_negatives) == (0, 1, 1)
    assert result.evidence_rejections == 1


def test_duplicate_correct_predictions_are_penalized_and_not_double_counted():
    frozen = suite(case())
    result = evaluate(frozen, responses(frozen, draft(fact(), fact(), fact())))
    assert (result.true_positives, result.false_positives, result.false_negatives) == (1, 2, 0)
    assert result.precision.numerator == 1 and result.precision.denominator == 3
    assert result.precision.value == "0.333333"
    assert result.recall.value == "1.000000"


def test_decimal_equality_does_not_require_identical_decimal_spelling():
    frozen = suite(case(facts=[gold(value="12500000.000")]))
    result = evaluate(frozen, responses(frozen, draft(fact(value="12500000.0"))))
    assert result.true_positives == 1


def test_missing_positive_facts_is_not_a_false_claim_of_abstention():
    frozen = suite(case())
    result = evaluate(frozen, responses(frozen, draft()))
    assert (result.true_positives, result.false_positives, result.false_negatives) == (0, 0, 1)
    assert result.precision.value is None and result.precision.denominator == 0
    assert result.recall.value == "0.000000"
    assert result.successful_abstentions == result.expected_abstentions == 0


def test_empty_gold_and_valid_empty_draft_are_explicit_abstention_without_fabricated_ratios():
    frozen = suite(case(facts=[]))
    result = evaluate(frozen, responses(frozen, draft()))
    assert result.successful_abstentions == result.expected_abstentions == 1
    assert result.precision.value is None and result.recall.value is None
    assert result.precision.denominator == result.recall.denominator == 0


@pytest.mark.parametrize(
    "raw",
    [
        "not JSON",
        '{"schema_version":"1.0","facts":[],"facts":[]}',
        '{"schema_version":"1.0","facts":[],"unexpected":true}',
        '{"schema_version":"1.0","facts":NaN}',
        '{"schema_version":"1.0","facts":[{"private":"sensitive parser body"}]}',
    ],
)
def test_invalid_response_is_never_a_successful_empty_gold_abstention(raw):
    frozen = suite(case(facts=[]))
    result = evaluate(frozen, responses(frozen, raw))
    assert result.invalid_responses == 1
    assert result.successful_abstentions == 0
    assert result.cases[0].invalid_response is True
    assert "sensitive parser body" not in result.model_dump_json()


def test_predictions_against_empty_gold_are_false_positives():
    frozen = suite(case(facts=[]))
    result = evaluate(frozen, responses(frozen, draft(fact())))
    assert result.false_positives == 1 and result.false_negatives == 0
    assert result.successful_abstentions == 0
    assert result.precision.value == "0.000000" and result.recall.value is None


def test_all_cases_and_data_origins_contribute_in_suite_order():
    frozen = suite(case(), case(case_id="issuer-b", data_origin="user_supplied", facts=[]))
    result = evaluate(frozen, responses(frozen, draft(fact()), draft()))
    assert [entry.case_id for entry in result.cases] == [entry.case_id for entry in frozen.cases]
    assert [entry.data_origin for entry in result.cases] == ["synthetic", "user_supplied"]
    assert result.true_positives == result.successful_abstentions == 1


@pytest.mark.parametrize("corruption", ["suite_hash", "document_hash", "missing", "extra"])
def test_mismatched_saved_response_binding_blocks_the_whole_evaluation(corruption):
    frozen = suite(case())
    saved = responses(frozen, draft(fact()))
    if corruption == "suite_hash":
        saved.suite_sha256 = "0" * 64
    elif corruption == "document_hash":
        saved.cases[0].document_sha256 = "0" * 64
    elif corruption == "missing":
        saved.cases.clear()
    else:
        saved.cases.append(saved.cases[0].model_copy(update={"case_id": "unexpected"}))
    with pytest.raises(BenchmarkInvalid, match="^DOCUMENT_BENCHMARK_INVALID$"):
        evaluate(frozen, saved)


@pytest.mark.parametrize("corruption", ["source_hash", "invalid_base64", "noncanonical_base64"])
def test_raw_identity_and_base64_are_validated_before_scoring(corruption):
    entry = case(raw=b"a")
    if corruption == "source_hash":
        entry.document_sha256 = "0" * 64
    elif corruption == "invalid_base64":
        entry.content_base64 = "!!!!"
    else:
        # A nonzero unused padding bit decodes to the same byte in permissive decoders.
        entry.content_base64 = "YR=="
    frozen = suite(entry)
    with pytest.raises(BenchmarkInvalid, match="^DOCUMENT_BENCHMARK_INVALID$"):
        evaluate(frozen, responses(frozen, draft()))


def test_case_and_gold_mutations_cannot_bypass_execution_boundary_validation():
    frozen = suite(case())
    saved = responses(frozen, draft(fact()))
    frozen.cases[0].expected_facts.append(gold(value="12500000.0"))
    with pytest.raises(BenchmarkInvalid, match="^DOCUMENT_BENCHMARK_INVALID$"):
        evaluate(frozen, saved)
    with pytest.raises(BenchmarkInvalid, match="^DOCUMENT_BENCHMARK_INVALID$"):
        canonical_hash(frozen)


def test_mutated_response_duplicate_cases_are_rejected():
    frozen = suite(case())
    saved = responses(frozen, draft(fact()))
    saved.cases.append(saved.cases[0])
    with pytest.raises(BenchmarkInvalid, match="^DOCUMENT_BENCHMARK_INVALID$"):
        evaluate(frozen, saved)


def test_eight_mib_suite_limit_is_checked_before_any_format_parser(monkeypatch):
    frozen = suite(*(case(b"x" * 1048576, case_id=f"issuer-{i}") for i in range(9)))
    parser = Mock(side_effect=AssertionError("Parser must not run"))
    monkeypatch.setattr(document_benchmark, "read_text_document", parser)
    with pytest.raises(BenchmarkInvalid, match="^DOCUMENT_BENCHMARK_INVALID$"):
        evaluate(frozen, responses(frozen, *(draft() for _ in range(9))))
    parser.assert_not_called()


def test_multibyte_draft_limit_is_in_bytes_and_not_only_characters():
    frozen = suite(case())
    saved = responses(frozen, "\U0001f600" * 65537)
    with pytest.raises(BenchmarkInvalid, match="^DOCUMENT_BENCHMARK_INVALID$"):
        evaluate(frozen, saved)


def test_unreadable_document_blocks_the_whole_benchmark_without_parser_details():
    frozen = suite(case(raw=b"not PDF: private source", format="pdf"))
    with pytest.raises(BenchmarkInvalid, match="^DOCUMENT_BENCHMARK_INVALID$"):
        evaluate(frozen, responses(frozen, draft()))


def test_gold_is_part_of_suite_identity_and_reference_response_cannot_be_reused():
    frozen = suite(case())
    saved = responses(frozen, draft(fact()))
    changed = deepcopy(frozen)
    changed.cases[0].expected_facts[0].currency = "USD"
    assert canonical_hash(changed) != canonical_hash(frozen)
    with pytest.raises(BenchmarkInvalid, match="^DOCUMENT_BENCHMARK_INVALID$"):
        evaluate(changed, saved)


def test_reversed_saved_response_order_cannot_switch_document_identity():
    frozen = suite(case(), case(case_id="second", facts=[]))
    saved = responses(frozen, draft(fact()), draft())
    saved.cases.reverse()
    result = evaluate(frozen, saved)
    assert result.true_positives == 1 and result.successful_abstentions == 1


def test_surrogate_annotation_is_redacted_and_never_echoed():
    frozen = suite(case())
    frozen.cases[0].issuer_label = "private\ud800body"
    with pytest.raises(BenchmarkInvalid, match="^DOCUMENT_BENCHMARK_INVALID$"):
        canonical_hash(frozen)

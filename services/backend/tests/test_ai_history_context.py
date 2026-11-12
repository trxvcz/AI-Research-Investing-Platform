"""Frozen history evidence protects attribution, arithmetic, dates and trend claims."""

import json
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError
from test_financial_history import ACC, annual_rows, fixture, row

from alphasense.ai_history_context import (
    AiHistoryInvalid,
    build_history_context,
    validate_history_context,
    validate_history_narrative,
)
from alphasense.ai_history_contracts import AiHistoryComparison, AiHistoryContext, AiHistoryFact
from alphasense.financial_history import FinancialHistory, build_financial_history
from alphasense.report_contracts import ReportContent, canonical_sha256, seal_report


def context_fixture(rows=None):
    report, snapshots = fixture(rows)
    history = build_financial_history(report, snapshots)
    return report, history, build_history_context(report, history)


def resign(value):
    raw = deepcopy(value)
    raw["context_sha256"] = canonical_sha256(
        {k: v for k, v in raw.items() if k != "context_sha256"}
    )
    return AiHistoryContext.model_validate(raw)


def narrative(index=4, direction="increase"):
    return {
        "summary": [
            {
                "kind": "trend",
                "text": "Wynik wzrósł względem poprzedniego okresu.",
                "evidence_indexes": [index],
                "direction": direction,
            }
        ],
        "strengths": [],
        "risks": [],
        "questions": [],
        "limitations": ["Zakres analizy jest ograniczony."],
    }


def test_build_dense_deduplicated_facts_and_comparisons():
    report, history, context = context_fixture()
    assert [e.index for e in context.evidence] == list(range(5))
    assert [e.value for e in context.evidence if isinstance(e, AiHistoryFact)] == [
        "150",
        "100",
        "120",
    ]
    assert context.evidence[0].report_observation_index == 0
    assert context.evidence[0].filing_accession == ACC
    assert isinstance(context.evidence[-1], AiHistoryComparison)
    assert context.evidence[-1].delta_value == "30"
    assert context.evidence[-1].delta_percent == "25.000000"
    assert validate_history_context(context, report) == context
    assert build_history_context(report, history) == context


def test_build_does_not_mutate_report_or_history():
    report, history, _ = context_fixture()
    before = (report.model_dump_json(), history.model_dump_json())
    build_history_context(report, history)
    assert (report.model_dump_json(), history.model_dump_json()) == before


def test_empty_history_keeps_all_available_current_data_without_trends():
    report, _, _ = context_fixture()
    history = FinancialHistory(
        report_id=report.report_id,
        revision=report.revision,
        report_checksum=report.checksum,
        as_of=report.input.as_of,
        series=[],
        limitations=["Archiwum nie zawiera historii."],
    )
    context = build_history_context(report, history)
    assert len(context.evidence) == 1 and context.evidence[0].filing_accession is None
    assert any("Brak porównywalnej historii" in text for text in context.limitations)
    with pytest.raises(AiHistoryInvalid):
        validate_history_narrative(context, json.dumps(narrative(0)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("report_checksum", "0" * 64),
        ("revision", 2),
        ("as_of", datetime(2030, 1, 1, tzinfo=UTC)),
    ],
)
def test_mutated_history_identity_refused(field, value):
    report, history, _ = context_fixture()
    with pytest.raises(AiHistoryInvalid):
        build_history_context(report, history.model_copy(update={field: value}))


@pytest.mark.parametrize(
    "mutation",
    ["delta", "percent", "anchor", "source", "availability", "duplicate", "filing", "unordered"],
)
def test_forged_history_never_becomes_evidence(mutation):
    report, history, _ = context_fixture()
    changed = history.model_copy(deep=True)
    series = changed.series[0]
    if mutation == "delta":
        series.points[-1].delta_value = "999"
    if mutation == "percent":
        series.points[-1].delta_percent = "999.000000"
    if mutation == "anchor":
        series.points[-1].value = "999"
    if mutation == "source":
        series.source_sha256 = "0" * 64
    if mutation == "availability":
        series.available_at = series.available_at.replace(year=2030)
    if mutation == "duplicate":
        changed.series.append(series)
    if mutation == "filing":
        series.points[-1].filing_date = series.points[-1].filing_date.replace(year=2030)
    if mutation == "unordered":
        series.points.reverse()
    with pytest.raises(AiHistoryInvalid):
        build_history_context(report, changed)


def test_hash_tampering_refused_even_if_shape_is_valid():
    report, _, context = context_fixture()
    changed = context.model_copy(deep=True)
    changed.limitations.append("Undeclared change")
    with pytest.raises(AiHistoryInvalid):
        validate_history_context(changed, report)


@pytest.mark.parametrize(
    "mutation",
    [
        "index",
        "reference",
        "math",
        "direction_source",
        "future",
        "duplicate_original",
        "original_value",
        "source",
    ],
)
def test_rehashed_context_tampering_still_refused(mutation):
    report, _, context = context_fixture()
    raw = context.model_dump(mode="json")
    if mutation == "index":
        raw["evidence"][1]["index"] = 10
    if mutation == "reference":
        raw["evidence"][-1]["previous_index"] = 4
    if mutation == "math":
        raw["evidence"][-1]["delta_value"] = "999"
    if mutation == "direction_source":
        raw["evidence"][1]["filing_accession"] = "0000000123-25-000002"
    if mutation == "future":
        raw["evidence"][1]["available_at"] = "2030-01-01T00:00:00Z"
    if mutation == "duplicate_original":
        raw["evidence"][1]["report_observation_index"] = 0
    if mutation == "original_value":
        raw["evidence"][0]["value"] = "999"
    if mutation == "source":
        raw["evidence"][1]["source"]["sha256"] = "0" * 64
    with pytest.raises((ValidationError, AiHistoryInvalid, ValueError)):
        validate_history_context(resign(raw), report)


def test_context_bound_to_exact_report_revision():
    report, _, context = context_fixture()
    content = report.model_dump(mode="python", exclude={"checksum", "input_sha256"})
    content["input"]["observations"][0]["value"] = 151
    different = seal_report(ReportContent.model_validate(content))
    with pytest.raises(AiHistoryInvalid):
        validate_history_context(context, different)


def test_valid_typed_trend_and_state_question():
    _, _, context = context_fixture()
    value = narrative()
    value["strengths"] = [
        {
            "kind": "state",
            "text": "Dostępny jest wynik roczny.",
            "evidence_indexes": [0],
            "direction": None,
        }
    ]
    value["questions"] = [
        {
            "kind": "question",
            "text": "Jakie czynniki wyjaśniają zmianę?",
            "evidence_indexes": [4],
            "direction": None,
        }
    ]
    result = validate_history_narrative(context, json.dumps(value))
    assert result.summary[0].direction == "increase"


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown",
        "direction",
        "fact_as_trend",
        "comparison_as_state",
        "question_in_summary",
        "two_comparisons",
        "missing_kind",
        "duplicate_refs",
        "digits",
        "url",
        "html",
        "order",
    ],
)
def test_invalid_narrative_refused(mutation):
    _, _, context = context_fixture()
    value = narrative()
    claim = value["summary"][0]
    if mutation == "unknown":
        claim["evidence_indexes"] = [63]
    if mutation == "direction":
        claim["direction"] = "decrease"
    if mutation == "fact_as_trend":
        claim["evidence_indexes"] = [0]
    if mutation == "comparison_as_state":
        claim.update(kind="state", direction=None)
    if mutation == "question_in_summary":
        claim.update(kind="question", direction=None)
    if mutation == "two_comparisons":
        claim["evidence_indexes"] = [3, 4]
    if mutation == "missing_kind":
        del claim["kind"]
    if mutation == "duplicate_refs":
        claim["evidence_indexes"] = [4, 4]
    if mutation == "digits":
        claim["text"] = "Wynik wzrósł o 25 procent."
    if mutation == "url":
        claim["text"] = "Zobacz https://evil.invalid"
    if mutation == "html":
        claim["text"] = "<b>Wynik</b>"
    if mutation == "order":
        claim["text"] = "Kup akcje."
    with pytest.raises(AiHistoryInvalid, match="AI_HISTORY_RESPONSE_INVALID"):
        validate_history_narrative(context, json.dumps(value))


def test_zero_negative_base_and_noncomparable_periods():
    rows = annual_rows()
    rows[0]["val"] = 0
    rows[1]["val"] = -10
    report, history, context = context_fixture(rows)
    changes = [e for e in context.evidence if isinstance(e, AiHistoryComparison)]
    assert all(
        e.delta_percent is None and e.comparison_reason == "NON_POSITIVE_BASE" for e in changes
    )
    assert validate_history_narrative(context, json.dumps(narrative(4, "increase")))
    rows = [
        row("2022-01-01", "2022-12-31", 100),
        row("2024-01-01", "2024-12-31", 120),
        row("2025-01-01", "2025-12-31", 150),
    ]
    _, _, context = context_fixture(rows)
    with pytest.raises(AiHistoryInvalid):
        validate_history_narrative(context, json.dumps(narrative(3)))


@pytest.mark.parametrize("raw", ['{"summary":[],"summary":[]}', '{"x":NaN}', "[]", "x" * 262145])
def test_malformed_bounded_json_rejected(raw):
    _, _, context = context_fixture()
    with pytest.raises(AiHistoryInvalid):
        validate_history_narrative(context, raw)


@pytest.mark.parametrize("value", [Decimal("1e1000000"), Decimal("1e-1000000")])
def test_decimal_exponents_never_expand(value):
    from alphasense.ai_history_context import _plain

    with pytest.raises(ValueError):
        _plain(value)


def test_original_past_observation_is_reused_instead_of_duplicated():
    report, history, _ = context_fixture()
    value = report.model_dump(mode="python", exclude={"checksum", "input_sha256"})
    previous = deepcopy(value["input"]["observations"][0])
    previous.update(
        value=120,
        period_start=datetime(2024, 1, 1, tzinfo=UTC),
        period_end=datetime(2024, 12, 31, tzinfo=UTC),
    )
    value["input"]["observations"].append(previous)
    updated = seal_report(ReportContent.model_validate(value))
    history = history.model_copy(update={"report_checksum": updated.checksum})
    context = build_history_context(updated, history)
    assert len(context.evidence) == 5
    originals = [
        e
        for e in context.evidence
        if isinstance(e, AiHistoryFact) and e.report_observation_index is not None
    ]
    assert [e.report_observation_index for e in originals] == [0, 2]
    assert sum(isinstance(e, AiHistoryFact) and e.value == "120" for e in context.evidence) == 1


def test_series_order_does_not_change_context_hash_or_indexes():
    report, history, _ = context_fixture()
    value = report.model_dump(mode="python", exclude={"checksum", "input_sha256"})
    second = deepcopy(value["input"]["observations"][0])
    second.update(
        metric="net_income",
        source_id="sec-edgar-net-income-v1",
        snapshot_id="01234567-1234-4567-8123-012345678999",
    )
    value["input"]["observations"].append(second)
    source = deepcopy(value["sources"][0])
    source.update(
        source_id=second["source_id"],
        snapshot_id=second["snapshot_id"],
        sha256="b" * 64,
        url="https://data.sec.gov/api/xbrl/companyconcept/CIK0000000123/us-gaap/NetIncomeLoss.json",
    )
    value["sources"].append(source)
    report = seal_report(ReportContent.model_validate(value))
    history = history.model_copy(deep=True, update={"report_checksum": report.checksum})
    history.series.append(
        history.series[0].model_copy(
            update={
                "metric": "net_income",
                "source_snapshot_id": second["snapshot_id"],
                "source_sha256": source["sha256"],
                "source_url": source["url"],
            }
        )
    )
    first = build_history_context(report, history)
    history.series.reverse()
    assert build_history_context(report, history) == first


def test_orphan_historical_fact_and_historical_future_to_anchor_refused():
    report, _, context = context_fixture()
    raw = context.model_dump(mode="json")
    raw["evidence"] = raw["evidence"][:3]
    with pytest.raises((ValidationError, ValueError)):
        resign(raw)
    raw = context.model_dump(mode="json")
    raw["evidence"][1]["period_start"] = "2025-01-01T00:00:00Z"
    raw["evidence"][1]["period_end"] = "2025-12-31T00:00:00Z"
    with pytest.raises((ValidationError, ValueError, AiHistoryInvalid)):
        validate_history_context(resign(raw), report)

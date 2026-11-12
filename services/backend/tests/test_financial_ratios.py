"""Ratio arithmetic and refusal invariants; no DB, provider or model calls."""

from copy import deepcopy
from datetime import timedelta
from decimal import localcontext
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_financial_history import fixture

from alphasense.financial_history import FinancialHistory, build_financial_history
from alphasense.financial_ratios import (
    FinancialRatios,
    FinancialRatiosInvalid,
    build_financial_ratios,
)


def ratio_history(**updates):
    report, archive = fixture()
    data = build_financial_history(report, archive).model_dump(mode="python")
    template = data["series"][0]
    result = []
    for metric, value in [
        ("revenue", "100"),
        ("net_income", "20"),
        ("operating_cash_flow", "30"),
        ("capital_expenditures", "10"),
    ]:
        series = deepcopy(template)
        series.update(metric=metric, source_snapshot_id=uuid4())
        for point in series["points"]:
            point["value"] = updates.get(metric, value)
        result.append(series)
    data["series"] = result
    return FinancialHistory.model_validate(data)


def by_metric(result, metric):
    return [item for item in result.ratios if item.metric == metric]


def mutate(history, metric, **changes):
    value = history.model_dump(mode="python")
    series = next(item for item in value["series"] if item["metric"] == metric)
    series.update(changes)
    return FinancialHistory.model_validate(value)


def test_four_formulas_three_periods_and_provenance():
    history = ratio_history()
    result = build_financial_ratios(history)
    assert len(result.ratios) == 12
    expected = {
        "net_margin": "20.000000",
        "operating_cash_flow_margin": "30.000000",
        "capex_to_revenue": "10.000000",
        "free_cash_flow_margin": "20.000000",
    }
    for item in result.ratios:
        assert item.value_percent == expected[item.metric]
        assert item.status == "available" and item.reason is None
        for operand in item.operands:
            series = next(s for s in history.series if s.metric == operand.metric)
            assert operand.source_snapshot_id == series.source_snapshot_id
            assert operand.source_sha256 == series.source_sha256
        assert item.available_at == history.as_of
    assert FinancialRatios.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize(
    ("net_income", "expected"),
    [
        ("1.234567885", "1.234568"),
        ("1.2345665", "1.234566"),
        ("1.2345675", "1.234568"),
        ("-1.2345665", "-1.234566"),
        ("-0.000000001", "0.000000"),
        ("0", "0.000000"),
        ("-20", "-20.000000"),
    ],
)
def test_half_even_and_negative_zero(net_income, expected):
    result = build_financial_ratios(ratio_history(net_income=net_income))
    assert by_metric(result, "net_margin")[0].value_percent == expected


def test_precision_does_not_follow_caller_decimal_context():
    with localcontext() as context:
        context.prec = 3
        result = build_financial_ratios(ratio_history(revenue="3", net_income="1"))
    assert by_metric(result, "net_margin")[0].value_percent == "33.333333"


@pytest.mark.parametrize("revenue", ["0", "-1"])
def test_nonpositive_revenue_does_not_become_percentage(revenue):
    result = build_financial_ratios(ratio_history(revenue=revenue))
    assert all(
        p.value_percent is None and p.reason == "NON_POSITIVE_REVENUE" and p.available_at is None
        for p in result.ratios
    )


def test_negative_cashflow_is_valid_negative_capex_not_assumed_outflow():
    result = build_financial_ratios(
        ratio_history(operating_cash_flow="-30", capital_expenditures="-10")
    )
    assert by_metric(result, "operating_cash_flow_margin")[0].value_percent == "-30.000000"
    for name in ("capex_to_revenue", "free_cash_flow_margin"):
        assert by_metric(result, name)[0].reason == "NEGATIVE_CAPEX"


@pytest.mark.parametrize("mode", ["absent", "empty"])
def test_missing_input(mode):
    history = ratio_history()
    data = history.model_dump(mode="python")
    if mode == "absent":
        data["series"] = [s for s in data["series"] if s["metric"] != "net_income"]
    else:
        data["series"][1].update(points=[], status="unavailable")
    result = build_financial_ratios(FinancialHistory.model_validate(data))
    assert all(
        p.reason == "MISSING_INPUT" and len(p.operands) == 1
        for p in by_metric(result, "net_margin")
    )


def test_exact_period_match_and_missing_precedence():
    history = ratio_history()
    series = history.series[1]
    points = [
        p.model_copy(update={"period_start": p.period_start + timedelta(days=1)})
        for p in series.points
    ]
    history = mutate(history, "net_income", points=points)
    result = build_financial_ratios(history)
    assert all(p.reason == "PERIOD_MISMATCH" for p in by_metric(result, "net_margin"))
    data = history.model_dump(mode="python")
    data["series"] = [s for s in data["series"] if s["metric"] != "revenue"]
    result = build_financial_ratios(FinancialHistory.model_validate(data))
    assert all(p.reason == "MISSING_INPUT" for p in result.ratios)


@pytest.mark.parametrize("accession", [None, "0000000123-25-000002"])
def test_filing_mismatch_before_denominator(accession):
    history = mutate(ratio_history(revenue="0"), "net_income", filing_accession=accession)
    result = build_financial_ratios(history)
    assert by_metric(result, "net_margin")[0].reason == "FILING_MISMATCH"
    assert by_metric(result, "capex_to_revenue")[0].reason == "NON_POSITIVE_REVENUE"


def test_availability_is_latest_used_source():
    history = ratio_history()
    earlier = history.as_of - timedelta(hours=1)
    history = mutate(history, "revenue", available_at=earlier)
    history = mutate(history, "net_income", available_at=earlier)
    result = build_financial_ratios(history)
    assert by_metric(result, "net_margin")[0].available_at == earlier
    assert by_metric(result, "operating_cash_flow_margin")[0].available_at == history.as_of


@pytest.mark.parametrize(
    "damage", ["identity", "value", "operand", "duplicate", "omission", "available_at", "reason"]
)
def test_model_rejects_forged_results(damage):
    result = build_financial_ratios(ratio_history()).model_dump(mode="python")
    if damage == "identity":
        result["report_checksum"] = "b" * 64
    elif damage == "value":
        result["ratios"][0]["value_percent"] = "99.000000"
    elif damage == "operand":
        result["ratios"][0]["operands"][0]["value"] = "0"
    elif damage == "duplicate":
        result["ratios"][1] = result["ratios"][0]
    elif damage == "omission":
        result["ratios"].pop()
    elif damage == "available_at":
        result["ratios"][0]["available_at"] += timedelta(seconds=1)
    else:
        result["ratios"][0]["reason"] = "MISSING_INPUT"
    with pytest.raises(ValidationError):
        FinancialRatios.model_validate(result)


@pytest.mark.parametrize(
    "damage", ["duplicate_metric", "duplicate_period", "future", "reversed", "unavailable_points"]
)
def test_refuse_malformed_history(damage):
    data = ratio_history().model_dump(mode="python")
    if damage == "duplicate_metric":
        data["series"][1]["metric"] = "revenue"
    elif damage == "duplicate_period":
        data["series"][0]["points"][1] = data["series"][0]["points"][0]
    elif damage == "future":
        data["series"][0]["available_at"] += timedelta(seconds=1)
    elif damage == "reversed":
        data["series"][0]["points"][0]["period_end"] = data["series"][0]["points"][0][
            "period_start"
        ]
    else:
        data["series"][0]["status"] = "unavailable"
    with pytest.raises(FinancialRatiosInvalid, match="RATIOS_HISTORY_INVALID"):
        build_financial_ratios(FinancialHistory.model_validate(data))


def test_extreme_magnitude_refused_without_silent_rounding_or_truncation():
    history = ratio_history(revenue="0." + "0" * 125 + "1", net_income="9" * 128)
    with pytest.raises(FinancialRatiosInvalid, match="RATIOS_VALUE_OUT_OF_RANGE"):
        build_financial_ratios(history)


def test_empty_history_has_no_fabricated_periods():
    history = ratio_history().model_copy(update={"series": []})
    assert build_financial_ratios(history).ratios == []


@pytest.mark.parametrize(
    ("net_income", "allowed"),
    [
        ("1" + "0" * 120, True),
        ("1" + "0" * 121, False),
        ("-" + "1" + "0" * 119, True),
        ("-" + "1" + "0" * 120, False),
    ],
)
def test_percent_text_exact_length_boundary(net_income, allowed):
    history = ratio_history(net_income=net_income)
    if allowed:
        result = by_metric(build_financial_ratios(history), "net_margin")[0]
        assert len(result.value_percent) == 128
    else:
        with pytest.raises(FinancialRatiosInvalid, match="RATIOS_VALUE_OUT_OF_RANGE"):
            build_financial_ratios(history)

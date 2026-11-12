"""Exact same-filing comparatives and refusal paths without DB, network or models."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from alphasense.financial_history import FinancialHistoryInvalid, build_financial_history
from alphasense.report_contracts import ReportContent, seal_report
from alphasense.snapshot_contracts import SnapshotRecord

CIK = "0000000123"
ACC = "0000000123-26-000001"
SID = "01234567-1234-4567-8123-012345678900"
IID = "01234567-1234-4567-8123-012345678901"
URL = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{CIK}/us-gaap/Revenues.json"
NOW = datetime(2026, 2, 10, tzinfo=UTC)


def row(start, end, value, **updates):
    result = {
        "start": start,
        "end": end,
        "val": value,
        "accn": ACC,
        "form": "10-K",
        "fp": "FY",
        "fy": 2025,
        "filed": "2026-02-05",
    }
    result.update(updates)
    return result


def annual_rows():
    return [
        row("2023-01-01", "2023-12-31", 100),
        row("2024-01-01", "2024-12-31", 120),
        row("2025-01-01", "2025-12-31", 150),
    ]


def fixture(rows=None, *, raw=None):
    rows = deepcopy(rows if rows is not None else annual_rows())
    content = json.loads((Path(__file__).parent / "fixtures/report.synthetic.json").read_text())
    content.pop("checksum")
    content.pop("input_sha256")
    content["input"].update(instrument_id=IID, data_origin="live", as_of=NOW.isoformat())
    anchor = content["input"]["observations"][0]
    latest = rows[-1]
    anchor.update(
        unit="currency",
        value=150,
        source_id="sec-edgar-revenue-v1",
        snapshot_id=SID,
        period_start=latest["start"] + "T00:00:00Z",
        period_end=latest["end"] + "T00:00:00Z",
        event_time="2026-02-05T12:00:00Z",
        available_at=NOW.isoformat(),
    )
    content["input"]["observations"][1]["period_start"] = anchor["period_start"]
    content["input"]["observations"][1]["period_end"] = anchor["period_end"]
    content["generated_at_utc"] = NOW.isoformat()
    payload = {"cik": 123, "taxonomy": "us-gaap", "tag": "Revenues", "units": {"USD": rows}}
    raw = raw if raw is not None else json.dumps(payload).encode()
    digest = hashlib.sha256(raw).hexdigest()
    content["sources"] = [
        {
            "source_id": anchor["source_id"],
            "snapshot_id": SID,
            "sha256": digest,
            "url": URL,
            "retrieved_at": NOW.isoformat(),
            "license": "synthetic local fixture",
        }
    ]
    report = seal_report(ReportContent.model_validate(content))
    record = SnapshotRecord(
        schema_version="1.0",
        snapshot_id=UUID(SID),
        instrument_id=UUID(IID),
        data_origin="live",
        source_id=anchor["source_id"],
        source_url=URL,
        license="synthetic local fixture",
        as_of=NOW,
        available_at=NOW,
        retrieved_at=NOW,
        created_at=NOW,
        media_type="application/json",
        sha256=digest,
        byte_length=len(raw),
    )
    return report, [(record, raw)]


def result(rows=None, **kwargs):
    report, snapshots = fixture(rows, **kwargs)
    return build_financial_history(report, snapshots).series[0]


def test_exact_three_periods_same_filing_and_current_availability():
    report, snapshots = fixture()
    before = report.model_dump(mode="json"), deepcopy(snapshots)
    history = build_financial_history(report, snapshots)
    series = history.series[0]
    assert history.report_checksum == report.checksum and series.status == "available"
    assert series.filing_accession == ACC and series.available_at == NOW
    assert [p.value for p in series.points] == ["100", "120", "150"]
    assert [p.delta_value for p in series.points] == [None, "20", "30"]
    assert [p.delta_percent for p in series.points] == [None, "20.000000", "25.000000"]
    assert series.points[0].comparison_reason == "NO_PRIOR_PERIOD"
    assert report.model_dump(mode="json") == before[0] and snapshots == before[1]
    assert history == build_financial_history(report, snapshots)


def test_canonical_sec_currency_unit_not_currency_code_is_used():
    report, snapshots = fixture()
    assert report.input.observations[0].unit == "currency"
    assert report.input.observations[0].currency == "USD"
    assert build_financial_history(report, snapshots).series[0].status == "available"
    content = report.model_dump(mode="python", exclude={"checksum", "input_sha256"})
    content["input"]["observations"][0]["unit"] = "ratio"
    non_currency = seal_report(ReportContent.model_validate(content))
    assert build_financial_history(non_currency, snapshots).series == []


@pytest.mark.parametrize("prior", [0, -20])
def test_zero_negative_base_preserved_without_growth_percentage(prior):
    series = result([row("2024-01-01", "2024-12-31", prior), row("2025-01-01", "2025-12-31", 150)])
    assert series.status == "partial" and series.points[0].value == str(prior)
    current = series.points[1]
    assert current.delta_value == str(150 - prior)
    assert current.delta_percent is None and current.comparison_reason == "NON_POSITIVE_BASE"


def test_half_even_six_places_and_noncalendar_52_53_week_years():
    rows = [
        row("2022-09-25", "2023-09-30", 3),
        row("2023-10-01", "2024-09-28", 4),
        row("2024-09-29", "2025-09-27", 150),
    ]
    series = result(rows)
    assert series.status == "available"
    assert series.points[1].delta_percent == "33.333333"
    assert series.points[2].delta_percent == "3650.000000"


def test_gap_never_relabelled_as_previous_year():
    rows = [row("2022-01-01", "2022-12-31", 100), row("2025-01-01", "2025-12-31", 150)]
    current = result(rows).points[-1]
    assert current.delta_value is None and current.delta_percent is None
    assert current.comparison_reason == "PERIODS_NOT_COMPARABLE"


def test_material_fiscal_length_change_is_not_a_growth_percentage():
    rows = [row("2024-02-01", "2024-12-31", 100), row("2025-01-01", "2025-12-31", 150)]
    current = result(rows).points[-1]
    assert current.delta_value is None and current.delta_percent is None
    assert current.comparison_reason == "PERIODS_NOT_COMPARABLE"


def test_more_than_three_periods_returns_only_newest_three():
    rows = [row("2022-01-01", "2022-12-31", 80), *annual_rows()]
    series = result(rows)
    assert [point.value for point in series.points] == ["100", "120", "150"]
    assert series.points[0].delta_value is None


def test_latest_filing_fy_not_required_to_match_comparative_year():
    assert result().status == "available"  # All rows have fy=2025.


def test_identical_duplicates_deduplicated():
    rows = annual_rows()
    rows.insert(1, dict(rows[0]))
    assert len(result(rows).points) == 3


def test_conflicting_duplicate_refuses_whole_series():
    rows = annual_rows()
    rows.insert(1, dict(rows[0], val=101))
    series = result(rows)
    assert series.status == "unavailable" and series.points == []
    assert series.reason == "HISTORY_FACT_AMBIGUOUS"


def test_overlapping_annual_context_refuses_whole_series():
    rows = annual_rows()
    rows.insert(1, row("2023-02-01", "2023-12-31", 90))
    assert result(rows).reason == "HISTORY_PERIOD_AMBIGUOUS"


def test_quarter_context_ignored_without_vetoing_annual():
    rows = annual_rows()
    rows.insert(0, row("2025-10-01", "2025-12-31", 40, fp="Q4"))
    assert result(rows).status == "available"


def test_newer_filing_comparative_excluded_using_anchor_event_time():
    rows = annual_rows()
    rows.insert(0, dict(rows[-1], accn="0000000123-27-000001", filed="2027-02-05"))
    assert result(rows).filing_accession == ACC


def test_multiple_eligible_anchor_accessions_refused():
    rows = annual_rows()
    rows.insert(0, dict(rows[-1], accn="0000000123-26-000002"))
    assert result(rows).reason == "HISTORY_ANCHOR_AMBIGUOUS"


def test_other_accession_values_not_used_for_missing_history():
    rows = [row("2023-01-01", "2023-12-31", 100, accn="0000000123-24-000001"), annual_rows()[-1]]
    series = result(rows)
    assert series.status == "partial" and [p.value for p in series.points] == ["150"]


@pytest.mark.parametrize(
    "change",
    [
        {"form": "10-K/A"},
        {"fp": "Q4"},
        {"filed": "2026-02-06"},
        {"val": False},
        {"val": "150"},
    ],
)
def test_invalid_or_unsupported_anchor_context_refuses(change):
    rows = annual_rows()
    rows[-1].update(change)
    assert result(rows).status == "unavailable"


def test_snapshot_integrity_and_identity_refused_without_raw_diagnostics():
    for change in (
        {"sha256": "0" * 64},
        {"byte_length": 1},
        {"instrument_id": UUID("01234567-1234-4567-8123-012345678902")},
        {"source_url": URL.replace("Revenues", "NetIncomeLoss")},
        {"retrieved_at": datetime(2027, 1, 1, tzinfo=UTC)},
    ):
        report, snapshots = fixture()
        record, raw = snapshots[0]
        series = build_financial_history(report, [(record.model_copy(update=change), raw)]).series[
            0
        ]
        assert series.status == "unavailable" and series.points == []


@pytest.mark.parametrize(
    "body",
    [
        b'{"cik":123,"cik":124}',
        b'{"units":{"USD":NaN}}',
        b"bad",
        b"[]",
        b"\xff",
        b'{"cik":123,"taxonomy":"us-gaap","tag":"NetIncomeLoss","units":{"USD":[]}}',
        b'{"cik":124,"taxonomy":"us-gaap","tag":"Revenues","units":{"USD":[]}}',
    ],
)
def test_bad_json_and_concept_identity_refuse(body):
    assert result(raw=body).status == "unavailable"


def test_non_usd_units_not_converted_or_substituted():
    _, snapshots = fixture()
    payload = json.loads(snapshots[0][1])
    payload["units"]["EUR"] = payload["units"].pop("USD")
    assert result(raw=json.dumps(payload).encode()).reason == "HISTORY_USD_UNAVAILABLE"


def test_non_sec_host_rejected_before_source_processing():
    report, snapshots = fixture()
    content = report.model_dump(mode="python", exclude={"checksum", "input_sha256"})
    content["sources"][0]["url"] = "https://data.sec.gov.evil.invalid/file.json"
    updated = seal_report(ReportContent.model_validate(content))
    with pytest.raises(FinancialHistoryInvalid, match="HISTORY_UNSUPPORTED_REPORT"):
        build_financial_history(updated, snapshots)


def test_pit_future_snapshot_asof_not_accepted():
    report, snapshots = fixture()
    record, raw = snapshots[0]
    changed = record.model_copy(update={"as_of": datetime(2027, 1, 1, tzinfo=UTC)})
    series = build_financial_history(report, [(changed, raw)]).series[0]
    assert series.reason == "HISTORY_SOURCE_INTEGRITY" and series.points == []


@pytest.mark.parametrize("token", ["1e1000000", "1e-1000000"])
def test_extreme_decimal_exponents_refused_before_fixed_format_allocation(token):
    _, snapshots = fixture()
    payload = json.loads(snapshots[0][1])
    payload["units"]["USD"][0]["val"] = "HUGE"
    raw = json.dumps(payload).replace('"HUGE"', token).encode()
    assert result(raw=raw).reason == "HISTORY_VALUE_INVALID"


def test_missing_snapshot_is_explicit_unavailable():
    report, _ = fixture()
    assert build_financial_history(report, []).series[0].reason == "HISTORY_SOURCE_MISSING"


def test_multiple_latest_report_anchors_same_end_are_not_arbitrarily_selected():
    report, snapshots = fixture()
    content = report.model_dump(mode="python", exclude={"checksum", "input_sha256"})
    other = dict(content["input"]["observations"][0])
    other["period_start"] = datetime(2025, 2, 1, tzinfo=UTC)
    content["input"]["observations"].append(other)
    updated = seal_report(ReportContent.model_validate(content))
    series = build_financial_history(updated, snapshots).series[0]
    assert series.points == [] and series.reason == "HISTORY_ANCHOR_AMBIGUOUS"


def test_synthetic_report_and_duplicate_snapshot_rejected():
    report, snapshots = fixture()
    with pytest.raises(FinancialHistoryInvalid, match="HISTORY_SOURCE_DUPLICATE"):
        build_financial_history(report, snapshots + snapshots)
    content = report.model_dump(mode="python", exclude={"checksum", "input_sha256"})
    content["input"]["data_origin"] = "synthetic"
    with pytest.raises(FinancialHistoryInvalid, match="HISTORY_UNSUPPORTED_REPORT"):
        build_financial_history(seal_report(ReportContent.model_validate(content)), snapshots)

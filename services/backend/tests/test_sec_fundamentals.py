"""Synthetic SEC shapes only: no downloaded company numbers or network activity."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from alphasense.contracts import AvailableObservation
from alphasense.instrument_contracts import InstrumentRecord
from alphasense.run_contracts import RunState
from alphasense.sec_contracts import SEC_SOURCE_IDS, SecFetchRequest, sec_url
from alphasense.sec_fundamentals import SecInputError, load_sec_input, parse_sec_submissions
from alphasense.snapshot_contracts import SnapshotRecord

CIK = "0000000123"
ACCESSION = "0000000123-24-000001"
REVENUE = "RevenueFromContractWithCustomerExcludingAssessedTax"
INSTRUMENT_ID = UUID("9b17a8f7-e21c-48ad-83f5-6b386f2c4412")
RETRIEVED = datetime(2024, 2, 3, 12, tzinfo=UTC)


def payloads() -> dict[str, dict[str, Any]]:
    def concept(tag: str, value: int) -> dict[str, Any]:
        return {
            "cik": 123,
            "entityName": "Synthetic SEC parser fixture",
            "taxonomy": "us-gaap",
            "tag": tag,
            "units": {
                "USD": [
                    {
                        "start": "2023-01-01",
                        "end": "2023-12-31",
                        "val": value,
                        "accn": ACCESSION,
                        "fy": 2023,
                        "fp": "FY",
                        "form": "10-K",
                        "filed": "2024-02-02",
                        "frame": "CY2023",
                    }
                ]
            },
        }

    return {
        "submissions": {
            "cik": CIK,
            "name": "Synthetic SEC parser fixture",
            "tickers": ["SYNTH-SEC"],
            "exchanges": ["Nasdaq"],
            "filings": {
                "recent": {
                    "accessionNumber": [ACCESSION],
                    "form": ["10-K"],
                    "reportDate": ["2023-12-31"],
                    "filingDate": ["2024-02-02"],
                    "acceptanceDateTime": ["2024-02-02T17:18:19Z"],
                }
            },
        },
        "revenue": concept(REVENUE, 100),
        "net_income": concept("NetIncomeLoss", 25),
    }


def bundle(
    data: dict[str, dict[str, Any]] | None = None,
    raw_overrides: dict[str, bytes] | None = None,
) -> tuple[RunState, InstrumentRecord, list[tuple[SnapshotRecord, bytes]]]:
    data = deepcopy(data if data is not None else payloads())
    instrument = InstrumentRecord(
        schema_version="1.0",
        instrument_id=INSTRUMENT_ID,
        symbol="SYNTH-SEC",
        exchange_mic="XNAS",
        currency="USD",
        display_name="Synthetic SEC parser fixture",
        asset_type="equity",
        data_origin="synthetic",
        as_of="2024-02-04T00:00:00Z",
        available_at=RETRIEVED,
        source_id="synthetic-registry",
        source_url=sec_url(SecFetchRequest(cik=CIK, resource="submissions")),
        license="generated fixture",
        created_at="2024-02-05T00:00:00Z",
    )
    snapshots = []
    for index, (role, payload) in enumerate(data.items(), 1):
        raw = (raw_overrides or {}).get(role, json.dumps(payload).encode("utf-8"))
        record = SnapshotRecord.model_validate(
            {
                "schema_version": "1.0",
                "snapshot_id": str(UUID(int=index)),
                "instrument_id": str(INSTRUMENT_ID),
                "data_origin": "synthetic",
                "source_id": SEC_SOURCE_IDS[role],
                "source_url": sec_url(
                    SecFetchRequest.model_validate({"cik": CIK, "resource": role})
                ),
                "license": "generated fixture",
                "as_of": RETRIEVED,
                "available_at": RETRIEVED,
                "retrieved_at": RETRIEVED,
                "media_type": "application/json",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "byte_length": len(raw),
                "created_at": "2024-02-05T00:00:00Z",
            }
        )
        snapshots.append((record, raw))
    state = RunState.model_validate(
        {
            "run_id": "64323f57-5584-488f-ae13-325fb2735a33",
            "instrument_id": str(INSTRUMENT_ID),
            "as_of": "2024-02-04T00:00:00Z",
            "snapshot_ids": [str(record.snapshot_id) for record, _raw in snapshots],
            "pipeline_version": "sec-fundamentals-v1",
            "data_origin": "synthetic",
            "sequence": 2,
            "status": "running",
            "current_step": "data",
            "completed_steps": [],
            "error_code": None,
            "error_reason": None,
            "report_revision_id": None,
            "report_status": None,
            "created_at": "2024-02-05T00:00:00Z",
            "updated_at": "2024-02-05T00:00:00Z",
        }
    )
    return state, instrument, snapshots


def test_golden_exact_sources_and_conservative_availability() -> None:
    state, identity, snapshots = bundle()
    result = load_sec_input(state, identity, snapshots)
    assert result.data_origin == "synthetic"
    revenue, income = result.observations
    assert isinstance(revenue, AvailableObservation) and isinstance(income, AvailableObservation)
    assert (revenue.value, income.value) == (100.0, 25.0)
    assert revenue.unit == "currency" and revenue.currency == "USD"
    assert revenue.event_time == datetime(2024, 2, 2, 17, 18, 19, tzinfo=UTC)
    assert revenue.available_at == RETRIEVED
    assert revenue.period_end == datetime(2023, 12, 31, tzinfo=UTC)
    assert revenue.snapshot_id == str(snapshots[1][0].snapshot_id)
    assert income.snapshot_id == str(snapshots[2][0].snapshot_id)
    assert load_sec_input(state, identity, list(reversed(snapshots))) == result


@pytest.mark.parametrize("value", [0, -25])
def test_real_zero_and_negative_income_are_preserved(value: int) -> None:
    data = payloads()
    data["net_income"]["units"]["USD"][0]["val"] = value
    state, identity, snapshots = bundle(data)
    assert load_sec_input(state, identity, snapshots).observations[1].value == value


def test_missing_fact_is_not_filled_with_zero_or_prior_year() -> None:
    data = payloads()
    data["net_income"]["units"]["USD"][0]["accn"] = "0000000123-23-000001"
    state, identity, snapshots = bundle(data)
    item = load_sec_input(state, identity, snapshots).observations[1]
    assert item.status == "missing" and item.value is None
    assert "latest" in item.reason


def test_no_current_facts_cannot_borrow_a_period() -> None:
    data = payloads()
    for role in ("revenue", "net_income"):
        data[role]["units"]["USD"] = []
    with pytest.raises(SecInputError, match="SEC_NO_ANNUAL_FACTS"):
        load_sec_input(*bundle(data))


@pytest.mark.parametrize("quarter_first", [False, True])
def test_quarter_context_in_same_annual_filing_does_not_veto_annual_fact(
    quarter_first: bool,
) -> None:
    data = payloads()
    for role in ("revenue", "net_income"):
        annual = data[role]["units"]["USD"][0]
        quarter = {**annual, "start": "2023-10-01", "val": 7}
        data[role]["units"]["USD"] = [quarter, annual] if quarter_first else [annual, quarter]
    result = load_sec_input(*bundle(data))
    assert [item.value for item in result.observations] == [100.0, 25.0]
    assert result.observations[0].period_start == datetime(2023, 1, 1, tzinfo=UTC)


def test_quarter_only_metric_is_missing_for_the_known_annual_period() -> None:
    data = payloads()
    data["revenue"]["units"]["USD"][0].update(start="2023-10-01", fp="Q4")
    result = load_sec_input(*bundle(data))
    assert result.observations[0].status == "missing"
    assert result.observations[0].value is None
    assert result.observations[0].period_start == datetime(2023, 1, 1, tzinfo=UTC)
    assert result.observations[1].value == 25


def test_only_quarter_contexts_cannot_be_relabelled_as_annual() -> None:
    data = payloads()
    for role in ("revenue", "net_income"):
        data[role]["units"]["USD"][0]["start"] = "2023-10-01"
    with pytest.raises(SecInputError, match="SEC_NO_ANNUAL_FACTS"):
        load_sec_input(*bundle(data))


@pytest.mark.parametrize(
    "field,value",
    [
        ("val", True),
        ("val", "100"),
        ("filed", "2024-02-01"),
        ("fp", "Q4"),
        ("form", "10-K/A"),
        ("start", "2023-02-30"),
        ("start", "2024-01-01"),
    ],
)
def test_selected_fact_bad_value_or_context_fails(field: str, value: Any) -> None:
    data = payloads()
    data["revenue"]["units"]["USD"][0][field] = value
    with pytest.raises(SecInputError):
        load_sec_input(*bundle(data))


@pytest.mark.parametrize("token", ["1e400", "1e-400", "9007199254740993", "NaN", "Infinity"])
def test_nonfinite_underflow_and_precision_loss_are_not_observations(token: str) -> None:
    data = payloads()
    raw = json.dumps(data["revenue"]).replace('"val": 100', '"val": ' + token).encode()
    with pytest.raises(SecInputError):
        load_sec_input(*bundle(data, {"revenue": raw}))


def test_identical_context_duplicates_deduplicate_but_conflicts_fail() -> None:
    data = payloads()
    rows = data["revenue"]["units"]["USD"]
    rows.append(deepcopy(rows[0]))
    assert load_sec_input(*bundle(data)).observations[0].value == 100
    rows[1]["val"] = 101
    with pytest.raises(SecInputError, match="SEC_FACT_AMBIGUOUS"):
        load_sec_input(*bundle(data))


def test_competing_annual_start_dates_and_currency_are_not_merged() -> None:
    data = payloads()
    data["net_income"]["units"]["USD"][0]["start"] = "2023-01-02"
    with pytest.raises(SecInputError, match="SEC_PERIOD_AMBIGUOUS"):
        load_sec_input(*bundle(data))
    data = payloads()
    data["revenue"]["units"] = {"EUR": data["revenue"]["units"]["USD"]}
    with pytest.raises(SecInputError, match="SEC_UNIT_UNSUPPORTED"):
        load_sec_input(*bundle(data))


@pytest.mark.parametrize(
    "field,value",
    [
        ("tickers", ["OTHER"]),
        ("exchanges", ["NYSE"]),
        ("exchanges", []),
        ("cik", 124),
    ],
)
def test_listing_and_cik_must_match_verified_identity(field: str, value: Any) -> None:
    data = payloads()
    data["submissions"][field] = value
    with pytest.raises(SecInputError):
        load_sec_input(*bundle(data))


@pytest.mark.parametrize(
    "column,value",
    [
        ("acceptanceDateTime", ["2024-02-02T17:18:19"]),
        ("acceptanceDateTime", ["2024-02-04T17:18:19Z"]),
        ("filingDate", []),
        ("accessionNumber", ["PRIVATE-BAD-ACCESSION"]),
    ],
)
def test_missing_or_future_acceptance_and_misaligned_arrays_fail(column: str, value: Any) -> None:
    data = payloads()
    data["submissions"]["filings"]["recent"][column] = value
    with pytest.raises(SecInputError) as error:
        load_sec_input(*bundle(data))
    assert "PRIVATE" not in str(error.value)


def test_later_amendment_is_blocked_instead_of_silently_ignored() -> None:
    data = payloads()
    recent = data["submissions"]["filings"]["recent"]
    extra = {
        "accessionNumber": "0000000123-24-000002",
        "form": "10-K/A",
        "reportDate": "2023-12-31",
        "filingDate": "2024-02-03",
        "acceptanceDateTime": "2024-02-03T01:00:00Z",
    }
    for key, value in extra.items():
        recent[key].append(value)
    with pytest.raises(SecInputError, match="SEC_AMENDMENT_UNSUPPORTED"):
        load_sec_input(*bundle(data))


def test_newer_annual_filing_does_not_fall_back_to_known_old_facts() -> None:
    data = payloads()
    recent = data["submissions"]["filings"]["recent"]
    recent["accessionNumber"][0] = "0000000123-24-000003"
    with pytest.raises(SecInputError, match="SEC_NO_ANNUAL_FACTS"):
        load_sec_input(*bundle(data))


@pytest.mark.parametrize(
    "raw",
    [
        b'{"cik":123,"cik":123}',
        b"[1,2]",
        b"\xff\x00",
        b'{"cik":NaN}',
    ],
)
def test_duplicate_keys_invalid_utf8_and_non_object_json_fail(raw: bytes) -> None:
    with pytest.raises(SecInputError):
        load_sec_input(*bundle(raw_overrides={"submissions": raw}))


def test_snapshot_bytes_first_seen_urls_and_set_are_integrity_boundaries() -> None:
    state, identity, snapshots = bundle()
    bad = list(snapshots)
    bad[0] = bad[0][0], bad[0][1] + b" "
    with pytest.raises(SecInputError, match="SEC_SNAPSHOT_BYTES"):
        load_sec_input(state, identity, bad)
    bad = list(snapshots)
    bad[0] = bad[0][0].model_copy(update={"available_at": RETRIEVED - timedelta(days=1)}), bad[0][1]
    with pytest.raises(SecInputError, match="SEC_PIT"):
        load_sec_input(state, identity, bad)
    bad = list(snapshots)
    bad[0] = (
        bad[0][0].model_copy(update={"source_url": "https://example.invalid/submissions"}),
        bad[0][1],
    )
    with pytest.raises(SecInputError, match="SEC_SOURCE_URL"):
        load_sec_input(state, identity, bad)
    with pytest.raises(SecInputError, match="SEC_SNAPSHOT_SET"):
        load_sec_input(state, identity, snapshots[:2])


def test_non_usd_or_unsupported_instrument_blocks_before_extraction() -> None:
    state, identity, snapshots = bundle()
    with pytest.raises(SecInputError, match="SEC_INPUT_CONTEXT"):
        load_sec_input(state, identity.model_copy(update={"currency": "EUR"}), snapshots)


def test_registration_helper_decodes_only_matching_cik() -> None:
    raw = json.dumps(payloads()["submissions"]).encode()
    assert parse_sec_submissions(raw, CIK)["name"] == "Synthetic SEC parser fixture"
    with pytest.raises(SecInputError, match="SEC_IDENTITY"):
        parse_sec_submissions(raw, "0000000124")
    with pytest.raises(SecInputError, match="SEC_SNAPSHOT_BYTES"):
        parse_sec_submissions(b" " * 1048577, CIK)


@pytest.mark.parametrize(
    "replacement", ["cash", "debt_current", "debt_noncurrent", "operating_cf", "capex"]
)
def test_v1_rejects_v2_resource_substituted_for_required_source(replacement: str) -> None:
    state, instrument, snapshots = bundle()
    record, raw = snapshots[-1]
    snapshots[-1] = (record.model_copy(update={"source_id": SEC_SOURCE_IDS[replacement]}), raw)
    with pytest.raises(SecInputError, match="SEC_SNAPSHOT_SET"):
        load_sec_input(state, instrument, snapshots)


def test_v1_rejects_missing_required_snapshot() -> None:
    state, instrument, snapshots = bundle()
    with pytest.raises(SecInputError, match="SEC_SNAPSHOT_SET"):
        load_sec_input(state, instrument, snapshots[:-1])

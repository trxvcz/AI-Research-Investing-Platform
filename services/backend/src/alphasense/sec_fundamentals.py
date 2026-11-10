"""Pure SEC annual-fact extraction over three immutable raw responses.

Reporting dates are represented as UTC midnight calendar dates, not publication
timestamps. Publication uses SEC acceptanceDateTime; availability is deliberately
the local raw-response retrieval time, so this parser cannot backdate knowledge.
"""

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import TypeAdapter, ValidationError

from alphasense.contracts import ResearchInput, Timestamp
from alphasense.instrument_contracts import InstrumentRecord
from alphasense.run_contracts import RunState
from alphasense.sec_contracts import SEC_PIPELINE, SEC_SOURCE_IDS, SecFetchRequest, sec_url
from alphasense.snapshot_contracts import SnapshotRecord

_EXCHANGES = {"Nasdaq": "XNAS", "NYSE": "XNYS"}
_ACCESSION = re.compile(r"[0-9]{10}-[0-9]{2}-[0-9]{6}")
_CONCEPT_URL = re.compile(
    r"https://data\.sec\.gov/api/xbrl/companyconcept/CIK([0-9]{10})/us-gaap/"
    r"(RevenueFromContractWithCustomerExcludingAssessedTax|Revenues|SalesRevenueNet|NetIncomeLoss)"
    r"\.json"
)
_SUBMISSIONS_URL = re.compile(r"https://data\.sec\.gov/submissions/CIK([0-9]{10})\.json")


class SecInputError(ValueError):
    """A stable input failure, without source bytes or personally identifying data."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SecInputError("SEC_INVALID_JSON")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise SecInputError("SEC_INVALID_JSON")


def _json(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object,
            parse_float=Decimal,
            parse_constant=_constant,
        )
        if not isinstance(value, dict):
            raise SecInputError("SEC_INPUT_SCHEMA")
        return value
    except SecInputError:
        raise
    except (UnicodeError, ValueError, TypeError, RecursionError, InvalidOperation):
        raise SecInputError("SEC_INVALID_JSON") from None


def _cik(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise SecInputError("SEC_IDENTITY")
    text = str(value)
    if not re.fullmatch(r"[0-9]{1,10}", text) or int(text) == 0:
        raise SecInputError("SEC_IDENTITY")
    return text.zfill(10)


def parse_sec_submissions(raw: bytes, cik: str) -> dict[str, Any]:
    """Strictly decode a response and bind it to a requested CIK before registration."""
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 1048576:
        raise SecInputError("SEC_SNAPSHOT_BYTES")
    if not isinstance(cik, str) or not re.fullmatch(r"[0-9]{10}", cik):
        raise SecInputError("SEC_IDENTITY")
    payload = _json(raw)
    if _cik(payload.get("cik")) != _cik(cik):
        raise SecInputError("SEC_IDENTITY")
    return payload


def _date(value: object) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise SecInputError("SEC_DATE")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise SecInputError("SEC_DATE") from None


def _midnight(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def _timestamp(value: object) -> datetime:
    try:
        return TypeAdapter(Timestamp).validate_python(value)
    except (ValidationError, ValueError, TypeError):
        raise SecInputError("SEC_ACCEPTANCE_TIME") from None


@dataclass(frozen=True)
class _Filing:
    accession: str
    report_date: date
    filing_date: date
    accepted_at: datetime
    form: str


def _filing(
    submissions: dict[str, Any], cik: str, instrument: InstrumentRecord, retrieved_at: datetime
) -> _Filing:
    if _cik(submissions.get("cik")) != cik:
        raise SecInputError("SEC_IDENTITY")
    tickers, exchanges = submissions.get("tickers"), submissions.get("exchanges")
    if (
        not isinstance(tickers, list)
        or not isinstance(exchanges, list)
        or not tickers
        or len(tickers) != len(exchanges)
        or any(not isinstance(item, str) for item in (*tickers, *exchanges))
        or not any(
            ticker == instrument.symbol and _EXCHANGES.get(exchange) == instrument.exchange_mic
            for ticker, exchange in zip(tickers, exchanges, strict=True)
        )
    ):
        raise SecInputError("SEC_LISTING_MISMATCH")
    try:
        recent = submissions["filings"]["recent"]
        keys = ("accessionNumber", "form", "reportDate", "filingDate", "acceptanceDateTime")
        columns = [recent[key] for key in keys]
        if (
            any(not isinstance(column, list) for column in columns)
            or len({len(column) for column in columns}) != 1
        ):
            raise SecInputError("SEC_SUBMISSIONS_SCHEMA")
        filings: list[_Filing] = []
        for accession, form, report, filed, accepted in zip(*columns, strict=True):
            if form not in ("10-K", "10-K/A"):
                continue
            if not isinstance(accession, str) or not _ACCESSION.fullmatch(accession):
                raise SecInputError("SEC_ACCESSION")
            report_date, filing_date = _date(report), _date(filed)
            accepted_at = _timestamp(accepted)
            if accepted_at > retrieved_at or _midnight(report_date) > accepted_at:
                raise SecInputError("SEC_PIT")
            if filing_date < report_date:
                raise SecInputError("SEC_DATE")
            filings.append(_Filing(accession, report_date, filing_date, accepted_at, form))
    except (KeyError, TypeError, AttributeError):
        raise SecInputError("SEC_SUBMISSIONS_SCHEMA") from None
    if not filings:
        raise SecInputError("SEC_NO_ANNUAL_FILING")
    latest_period = max(item.report_date for item in filings)
    latest = [item for item in filings if item.report_date == latest_period]
    selected = max(latest, key=lambda item: item.accepted_at)
    if selected.form == "10-K/A":
        raise SecInputError("SEC_AMENDMENT_UNSUPPORTED")
    if any(item != selected and item.accepted_at == selected.accepted_at for item in latest):
        raise SecInputError("SEC_ANNUAL_AMBIGUOUS")
    return selected


def _number(value: object) -> tuple[Decimal, float]:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise SecInputError("SEC_VALUE")
    exact = Decimal(value)
    if not exact.is_finite():
        raise SecInputError("SEC_VALUE")
    try:
        number = float(exact)
        if not math.isfinite(number) or Decimal(str(number)) != exact:
            raise SecInputError("SEC_VALUE_PRECISION")
    except (OverflowError, InvalidOperation):
        raise SecInputError("SEC_VALUE_PRECISION") from None
    return exact, 0.0 if number == 0 else number


def _facts(
    payload: dict[str, Any], cik: str, tag: str, filing: _Filing
) -> tuple[date, date, float] | None:
    if _cik(payload.get("cik")) != cik:
        raise SecInputError("SEC_IDENTITY")
    if payload.get("taxonomy") != "us-gaap" or payload.get("tag") != tag:
        raise SecInputError("SEC_CONCEPT_MISMATCH")
    units = payload.get("units")
    if not isinstance(units, dict):
        raise SecInputError("SEC_FACT_SCHEMA")
    rows = units.get("USD")
    if rows is None:
        raise SecInputError("SEC_UNIT_UNSUPPORTED")
    if not isinstance(rows, list):
        raise SecInputError("SEC_FACT_SCHEMA")
    values: dict[tuple[date, date], tuple[Decimal, float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise SecInputError("SEC_FACT_SCHEMA")
        if row.get("accn") != filing.accession:
            continue
        if row.get("form") != "10-K":
            raise SecInputError("SEC_FACT_CONTEXT")
        if _date(row.get("filed")) != filing.filing_date:
            raise SecInputError("SEC_FACT_CONTEXT")
        start, end = _date(row.get("start")), _date(row.get("end"))
        if end != filing.report_date:
            continue  # Same filing can contain comparatives; never substitute them.
        if start > end:
            raise SecInputError("SEC_DATE")
        if not 300 <= (end - start).days <= 400:
            # The same 10-K can disclose annual and quarter-to-date contexts.
            # Extract annual candidates only; a short context must not veto a
            # valid annual fact or be silently relabelled as one.
            continue
        if row.get("fp") != "FY":
            raise SecInputError("SEC_FACT_CONTEXT")
        exact, number = _number(row.get("val"))
        key = start, end
        if key in values and values[key][0] != exact:
            raise SecInputError("SEC_FACT_AMBIGUOUS")
        values[key] = exact, number
    if len(values) > 1:
        raise SecInputError("SEC_PERIOD_AMBIGUOUS")
    if not values:
        return None
    (start, end), (_exact, number) = next(iter(values.items()))
    return start, end, number


def load_sec_input(
    state: RunState,
    instrument: InstrumentRecord,
    snapshots: list[tuple[SnapshotRecord, bytes]],
) -> ResearchInput:
    try:
        state = RunState.model_validate(state.model_dump(mode="python", warnings=False))
        instrument = InstrumentRecord.model_validate(
            instrument.model_dump(mode="python", warnings=False)
        )
    except (ValidationError, ValueError, TypeError):
        raise SecInputError("SEC_INPUT_CONTEXT") from None
    if (
        state.pipeline_version != SEC_PIPELINE
        or state.instrument_id != instrument.instrument_id
        or state.data_origin != instrument.data_origin
        or instrument.asset_type != "equity"
        or instrument.currency != "USD"
        or instrument.exchange_mic not in ("XNAS", "XNYS")
        or state.as_of > state.created_at
    ):
        raise SecInputError("SEC_INPUT_CONTEXT")
    if (
        len(snapshots) != 3
        or len(state.snapshot_ids) != 3
        or {item.snapshot_id for item, _raw in snapshots} != set(state.snapshot_ids)
    ):
        raise SecInputError("SEC_SNAPSHOT_SET")
    by_role: dict[str, tuple[SnapshotRecord, dict[str, Any]]] = {}
    role_for_source = {
        SEC_SOURCE_IDS[role]: role for role in ("submissions", "revenue", "net_income")
    }
    urls: dict[str, str] = {}
    for record, raw in snapshots:
        try:
            record = SnapshotRecord.model_validate(record.model_dump(mode="python", warnings=False))
        except (ValidationError, ValueError, TypeError):
            raise SecInputError("SEC_INPUT_CONTEXT") from None
        role = role_for_source.get(record.source_id)
        if role is None or role in by_role:
            raise SecInputError("SEC_SNAPSHOT_SET")
        if (
            record.instrument_id != state.instrument_id
            or record.data_origin != state.data_origin
            or record.media_type != "application/json"
        ):
            raise SecInputError("SEC_INPUT_IDENTITY")
        if (
            not isinstance(raw, bytes)
            or len(raw) != record.byte_length
            or hashlib.sha256(raw).hexdigest() != record.sha256
        ):
            raise SecInputError("SEC_SNAPSHOT_BYTES")
        if (
            record.available_at != record.retrieved_at
            or record.retrieved_at > state.as_of
            or record.as_of > state.as_of
        ):
            raise SecInputError("SEC_PIT")
        urls[role] = str(record.source_url)
        by_role[role] = record, _json(raw)
    submissions_match = _SUBMISSIONS_URL.fullmatch(urls["submissions"])
    revenue_match = _CONCEPT_URL.fullmatch(urls["revenue"])
    income_match = _CONCEPT_URL.fullmatch(urls["net_income"])
    if submissions_match is None or revenue_match is None or income_match is None:
        raise SecInputError("SEC_SOURCE_URL")
    cik = submissions_match[1]
    if (
        revenue_match[1] != cik
        or income_match[1] != cik
        or income_match[2] != "NetIncomeLoss"
        or revenue_match[2] == "NetIncomeLoss"
        or cik == "0000000000"
    ):
        raise SecInputError("SEC_SOURCE_URL")
    # Compare against the shared URL constructor as well as parsing each role.
    for role in by_role:
        request = SecFetchRequest.model_validate(
            dict(
                cik=cik,
                resource=role,
                revenue_concept=revenue_match[2],
            )
        )
        if urls[role] != sec_url(request):
            raise SecInputError("SEC_SOURCE_URL")
    filing = _filing(
        by_role["submissions"][1], cik, instrument, by_role["submissions"][0].retrieved_at
    )
    if any(record.retrieved_at < filing.accepted_at for record, _payload in by_role.values()):
        raise SecInputError("SEC_PIT")
    facts = {
        "revenue": _facts(by_role["revenue"][1], cik, revenue_match[2], filing),
        "net_income": _facts(by_role["net_income"][1], cik, "NetIncomeLoss", filing),
    }
    contexts = {(value[0], value[1]) for value in facts.values() if value is not None}
    if not contexts:
        raise SecInputError("SEC_NO_ANNUAL_FACTS")
    if len(contexts) != 1:
        raise SecInputError("SEC_PERIOD_AMBIGUOUS")
    start, end = next(iter(contexts))
    observations: list[dict[str, Any]] = []
    for metric, value in facts.items():
        base: dict[str, Any] = dict(
            metric=metric,
            unit="currency",
            currency="USD",
            period_start=_midnight(start),
            period_end=_midnight(end),
        )
        if value is None:
            base.update(
                status="missing",
                value=None,
                reason="No matching USD fact for the latest accepted annual filing",
            )
        else:
            record = by_role[metric][0]
            base.update(
                status="available",
                value=value[2],
                source_id=record.source_id,
                snapshot_id=str(record.snapshot_id),
                event_time=filing.accepted_at,
                available_at=record.retrieved_at,
            )
        observations.append(base)
    try:
        return ResearchInput.model_validate(
            dict(
                schema_version="1.0",
                instrument_id=str(state.instrument_id),
                asset_type="equity",
                as_of=state.as_of,
                data_origin=state.data_origin,
                observations=observations,
            )
        )
    except (ValidationError, ValueError, TypeError):
        raise SecInputError("SEC_INPUT_SCHEMA") from None

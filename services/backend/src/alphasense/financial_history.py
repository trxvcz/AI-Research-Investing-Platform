"""Three annual comparatives from exact archived SEC sources; no fetching or inference."""

import hashlib
import re
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, ValidationError

from alphasense.contracts import AvailableObservation, Contract, Timestamp
from alphasense.document_contracts import CalendarDate
from alphasense.report_contracts import ReportRevision, ReportUUID, Sha256, SourceProvenance
from alphasense.sec_fundamentals import SecInputError, _cik, _date, _json
from alphasense.snapshot_contracts import SnapshotRecord

Metric = Literal["revenue", "net_income", "operating_cash_flow", "capital_expenditures"]
DecimalString = Annotated[
    str,
    StringConstraints(strict=True, max_length=128, pattern=r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$"),
]
PercentString = Annotated[
    str, StringConstraints(strict=True, max_length=128, pattern=r"^-?(?:0|[1-9][0-9]*)\.[0-9]{6}$")
]
ComparisonReason = Literal["NO_PRIOR_PERIOD", "PERIODS_NOT_COMPARABLE", "NON_POSITIVE_BASE"]
_TAGS: dict[Metric, set[str]] = {
    "revenue": {
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    },
    "net_income": {"NetIncomeLoss"},
    "operating_cash_flow": {"NetCashProvidedByUsedInOperatingActivities"},
    "capital_expenditures": {"PaymentsToAcquirePropertyPlantAndEquipment"},
}
_URL = re.compile(
    r"https://data\.sec\.gov/api/xbrl/companyconcept/CIK([0-9]{10})/us-gaap/([A-Za-z]+)\.json"
)
_ACCESSION = re.compile(r"[0-9]{10}-[0-9]{2}-[0-9]{6}")


class FinancialHistoryPoint(Contract):
    period_start: CalendarDate
    period_end: CalendarDate
    value: DecimalString
    filing_date: CalendarDate
    delta_value: DecimalString | None
    delta_percent: PercentString | None
    comparison_reason: ComparisonReason | None


class FinancialHistorySeries(Contract):
    metric: Metric
    currency: Literal["USD"] = "USD"
    status: Literal["available", "partial", "unavailable"]
    reason: str | None
    source_snapshot_id: ReportUUID
    source_sha256: Sha256
    source_url: str
    available_at: Timestamp
    filing_accession: str | None
    points: Annotated[list[FinancialHistoryPoint], Field(max_length=3)]


class FinancialHistory(Contract):
    report_id: ReportUUID
    revision: Annotated[int, Field(strict=True, ge=1)]
    report_checksum: Sha256
    as_of: Timestamp
    methodology_version: Literal["sec-comparatives-v1"] = "sec-comparatives-v1"
    basis: Literal["latest_filing_comparatives"] = "latest_filing_comparatives"
    series: Annotated[list[FinancialHistorySeries], Field(max_length=4)]
    limitations: Annotated[list[str], Field(min_length=1, max_length=8)]


class FinancialHistoryInvalid(ValueError):
    """Stable refusal without raw data or diagnostics."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise FinancialHistoryInvalid("HISTORY_VALUE_INVALID")
    result = Decimal(value)
    if (
        not result.is_finite()
        or len(result.as_tuple().digits) > 128
        or not isinstance(result.as_tuple().exponent, int)
        or int(result.as_tuple().exponent) < -127
        or abs(result.adjusted()) > 127
        or len(format(result, "f")) > 128
    ):
        raise FinancialHistoryInvalid("HISTORY_VALUE_INVALID")
    return result


def _plain(value: Decimal) -> str:
    if value == 0:
        return "0"
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def _annual(start: date, end: date) -> bool:
    return 300 <= (end - start).days <= 400


def _points(values: dict[tuple[date, date], Decimal], filed: date) -> list[FinancialHistoryPoint]:
    ordered = sorted(values, key=lambda key: (key[1], key[0]))
    for previous_period, current_period in zip(ordered, ordered[1:], strict=False):
        if current_period[0] <= previous_period[1]:
            raise FinancialHistoryInvalid("HISTORY_PERIOD_AMBIGUOUS")
    selected = ordered[-3:]
    result = []
    for index, (start, end) in enumerate(selected):
        delta = percent = None
        reason: ComparisonReason | None = "NO_PRIOR_PERIOD"
        if index:
            prior_start, prior_end = selected[index - 1]
            if (
                start != prior_end + timedelta(days=1)
                or abs((end - start).days - (prior_end - prior_start).days) > 8
            ):
                reason = "PERIODS_NOT_COMPARABLE"
            else:
                with localcontext() as context:
                    context.prec = 300
                    current, prior = values[(start, end)], values[(prior_start, prior_end)]
                    delta = _plain(current - prior)
                    if prior <= 0:
                        reason = "NON_POSITIVE_BASE"
                    else:
                        value = ((current - prior) / prior * 100).quantize(
                            Decimal("0.000001"), rounding=ROUND_HALF_EVEN
                        )
                        percent = format(abs(value) if value == 0 else value, ".6f")
                        reason = None
        result.append(
            FinancialHistoryPoint(
                period_start=start,
                period_end=end,
                value=_plain(values[(start, end)]),
                filing_date=filed,
                delta_value=delta,
                delta_percent=percent,
                comparison_reason=reason,
            )
        )
    return result


def _series_points(
    report: ReportRevision,
    metric: Metric,
    anchor: AvailableObservation,
    source: SourceProvenance,
    snapshot: tuple[SnapshotRecord, bytes] | None,
) -> tuple[str, list[FinancialHistoryPoint]]:
    if snapshot is None:
        raise FinancialHistoryInvalid("HISTORY_SOURCE_MISSING")
    record, raw = snapshot
    record = SnapshotRecord.model_validate(record.model_dump(mode="python", warnings=False))
    match = _URL.fullmatch(str(record.source_url))
    if (
        match is None
        or match[2] not in _TAGS[metric]
        or str(record.instrument_id) != report.input.instrument_id
        or record.data_origin != "live"
        or record.media_type != "application/json"
        or str(record.snapshot_id) != source.snapshot_id
        or record.source_id != source.source_id
        or record.sha256 != source.sha256
        or str(record.source_url) != str(source.url)
        or record.retrieved_at != source.retrieved_at
        or record.available_at != record.retrieved_at
        or record.retrieved_at > report.input.as_of
        or record.as_of > report.input.as_of
        or record.retrieved_at != anchor.available_at
        or anchor.event_time > record.retrieved_at
        or not isinstance(raw, bytes)
        or len(raw) != record.byte_length
        or hashlib.sha256(raw).hexdigest() != record.sha256
    ):
        raise FinancialHistoryInvalid("HISTORY_SOURCE_INTEGRITY")
    payload = _json(raw)
    if (
        _cik(payload.get("cik")) != match[1]
        or payload.get("tag") != match[2]
        or payload.get("taxonomy") != "us-gaap"
    ):
        raise FinancialHistoryInvalid("HISTORY_CONCEPT_MISMATCH")
    units = payload.get("units")
    rows = units.get("USD") if isinstance(units, dict) else None
    if not isinstance(rows, list):
        raise FinancialHistoryInvalid("HISTORY_USD_UNAVAILABLE")
    # Only a matching annual anchor can choose a filing. Later filings must not
    # replace the value/version already bound to the source report.
    candidates: set[tuple[str, date]] = set()
    start, end = anchor.period_start.date(), anchor.period_end.date()
    for row in rows:
        if not isinstance(row, dict):
            raise FinancialHistoryInvalid("HISTORY_FACT_SCHEMA")
        if row.get("start") != start.isoformat() or row.get("end") != end.isoformat():
            continue
        if row.get("form") != "10-K" or row.get("fp") != "FY":
            continue
        if _decimal(row.get("val")) != Decimal(str(anchor.value)):
            continue
        accession = row.get("accn")
        filed = _date(row.get("filed"))
        if not isinstance(accession, str) or not _ACCESSION.fullmatch(accession):
            raise FinancialHistoryInvalid("HISTORY_FILING_INVALID")
        if filed > anchor.event_time.date() or filed < end:
            continue
        candidates.add((accession, filed))
    if len(candidates) != 1:
        raise FinancialHistoryInvalid("HISTORY_ANCHOR_AMBIGUOUS")
    accession, filed = next(iter(candidates))
    values: dict[tuple[date, date], Decimal] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise FinancialHistoryInvalid("HISTORY_FACT_SCHEMA")
        if row.get("accn") != accession:
            continue
        row_start, row_end = _date(row.get("start")), _date(row.get("end"))
        if row_start > row_end:
            raise FinancialHistoryInvalid("HISTORY_PERIOD_INVALID")
        if row_end > end or not _annual(row_start, row_end):
            continue
        if row.get("form") != "10-K" or row.get("fp") != "FY" or _date(row.get("filed")) != filed:
            raise FinancialHistoryInvalid("HISTORY_FILING_CONTEXT")
        key, value = (row_start, row_end), _decimal(row.get("val"))
        if key in values and values[key] != value:
            raise FinancialHistoryInvalid("HISTORY_FACT_AMBIGUOUS")
        values[key] = value
    if values.get((start, end)) != Decimal(str(anchor.value)):
        raise FinancialHistoryInvalid("HISTORY_ANCHOR_MISMATCH")
    return accession, _points(values, filed)


def build_financial_history(
    report: ReportRevision, snapshots: list[tuple[SnapshotRecord, bytes]]
) -> FinancialHistory:
    """Calculate a sidecar without mutating reports, archives, AI or provider policy."""
    try:
        checked = ReportRevision.model_validate(report.model_dump(mode="python"))
        if checked.input.data_origin != "live" or not checked.sources:
            raise FinancialHistoryInvalid("HISTORY_UNSUPPORTED_REPORT")
        for source in checked.sources:
            if not str(source.url).startswith(("https://data.sec.gov/", "https://www.sec.gov/")):
                raise FinancialHistoryInvalid("HISTORY_UNSUPPORTED_REPORT")
        if not isinstance(snapshots, list) or len(snapshots) > 1000:
            raise FinancialHistoryInvalid("HISTORY_INPUT_INVALID")
        by_id = {str(record.snapshot_id): (record, raw) for record, raw in snapshots}
        if len(by_id) != len(snapshots):
            raise FinancialHistoryInvalid("HISTORY_SOURCE_DUPLICATE")
        sources = {(s.source_id, s.snapshot_id): s for s in checked.sources}
        results = []
        for metric in _TAGS:
            anchors = [
                o
                for o in checked.input.observations
                if isinstance(o, AvailableObservation)
                and o.metric == metric
                and o.currency == "USD"
                and o.unit == "currency"
                and _annual(o.period_start.date(), o.period_end.date())
            ]
            if not anchors:
                continue
            anchor = max(anchors, key=lambda o: o.period_end)
            source = sources[(anchor.source_id, anchor.snapshot_id)]
            accession = None
            points: list[FinancialHistoryPoint] = []
            reason = None
            try:
                if sum(o.period_end == anchor.period_end for o in anchors) != 1:
                    raise FinancialHistoryInvalid("HISTORY_ANCHOR_AMBIGUOUS")
                accession, points = _series_points(
                    checked, metric, anchor, source, by_id.get(source.snapshot_id)
                )
                if len(points) < 3:
                    reason = "HISTORY_FEWER_PERIODS"
            except (FinancialHistoryInvalid, SecInputError, ValidationError) as error:
                reason = getattr(error, "code", "HISTORY_SOURCE_INTEGRITY")
            results.append(
                FinancialHistorySeries(
                    metric=metric,
                    status="available"
                    if len(points) == 3
                    else ("partial" if points else "unavailable"),
                    reason=reason,
                    source_snapshot_id=UUID(source.snapshot_id),
                    source_sha256=source.sha256,
                    source_url=str(source.url),
                    available_at=source.retrieved_at,
                    filing_accession=accession,
                    points=points,
                )
            )
        return FinancialHistory(
            report_id=checked.report_id,
            revision=checked.revision,
            report_checksum=checked.checksum,
            as_of=checked.input.as_of,
            series=results,
            limitations=[
                "Dane porównawcze z tego samego sprawozdania; mogą zawierać przekształcenia. "
                "To nie jest odtworzenie wiedzy inwestora w dawnym roku.",
                "Historia nie jest jeszcze wejściem zapisanej analizy AI. "
                "Zmiany obliczono deterministycznie na danych archiwum SEC.",
            ],
        )
    except FinancialHistoryInvalid:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise FinancialHistoryInvalid("HISTORY_INPUT_INVALID") from None

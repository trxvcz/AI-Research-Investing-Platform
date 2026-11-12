"""Exact descriptive ratios from one filing's report-bound annual comparatives."""

from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from alphasense.contracts import Contract, Timestamp
from alphasense.document_contracts import CalendarDate
from alphasense.financial_history import (
    DecimalString,
    FinancialHistory,
    FinancialHistoryPoint,
    FinancialHistorySeries,
    Metric,
    PercentString,
)
from alphasense.report_contracts import ReportUUID, Sha256

RatioMetric = Literal[
    "net_margin", "operating_cash_flow_margin", "capex_to_revenue", "free_cash_flow_margin"
]
RatioReason = Literal[
    "MISSING_INPUT",
    "PERIOD_MISMATCH",
    "FILING_MISMATCH",
    "NON_POSITIVE_REVENUE",
    "NEGATIVE_CAPEX",
]
Text = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2000)]
_REQUIRED: dict[RatioMetric, tuple[Metric, ...]] = {
    "net_margin": ("revenue", "net_income"),
    "operating_cash_flow_margin": ("revenue", "operating_cash_flow"),
    "capex_to_revenue": ("revenue", "capital_expenditures"),
    "free_cash_flow_margin": ("revenue", "operating_cash_flow", "capital_expenditures"),
}


class FinancialRatiosInvalid(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RatioOperand(Contract):
    metric: Metric
    value: DecimalString
    source_snapshot_id: ReportUUID
    source_sha256: Sha256


class FinancialRatioPoint(Contract):
    metric: RatioMetric
    period_start: CalendarDate
    period_end: CalendarDate
    status: Literal["available", "unavailable"]
    value_percent: PercentString | None
    reason: RatioReason | None
    available_at: Timestamp | None
    operands: Annotated[list[RatioOperand], Field(max_length=3)]

    @model_validator(mode="after")
    def state(self) -> Self:
        if self.period_start > self.period_end:
            raise ValueError("Invalid period")
        if len({o.metric for o in self.operands}) != len(self.operands):
            raise ValueError("Duplicate operand")
        if self.status == "available":
            if self.value_percent is None or self.reason is not None or self.available_at is None:
                raise ValueError("Available ratio requires value and availability")
        elif self.value_percent is not None or self.reason is None or self.available_at is not None:
            raise ValueError("Unavailable ratio must explain missing result")
        return self


def _history_index(history: FinancialHistory) -> dict[Metric, FinancialHistorySeries]:
    checked = FinancialHistory.model_validate(history.model_dump(mode="python"))
    indexed: dict[Metric, FinancialHistorySeries] = {}
    for series in checked.series:
        if series.metric in indexed or series.available_at > checked.as_of:
            raise FinancialRatiosInvalid("RATIOS_HISTORY_INVALID")
        indexed[series.metric] = series
        seen = set()
        for point in series.points:
            period = (point.period_start, point.period_end)
            if (
                period in seen
                or not 300 <= (point.period_end - point.period_start).days <= 400
                or point.filing_date > series.available_at.date()
                or point.period_end > point.filing_date
            ):
                raise FinancialRatiosInvalid("RATIOS_HISTORY_INVALID")
            seen.add(period)
        if series.status == "unavailable" and series.points:
            raise FinancialRatiosInvalid("RATIOS_HISTORY_INVALID")
    return indexed


def _percent(metric: RatioMetric, values: dict[Metric, Decimal]) -> str:
    with localcontext() as context:
        context.prec = 512
        numerator = values[_REQUIRED[metric][1]]
        if metric == "free_cash_flow_margin":
            numerator -= values["capital_expenditures"]
        result = (numerator / values["revenue"] * 100).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_EVEN
        )
        if result == 0:
            result = abs(result)
        text = format(result, ".6f")
    if len(text) > 128:
        raise FinancialRatiosInvalid("RATIOS_VALUE_OUT_OF_RANGE")
    return text


def _point(
    metric: RatioMetric,
    period: tuple[date, date],
    indexed: dict[Metric, FinancialHistorySeries],
) -> FinancialRatioPoint:
    required = _REQUIRED[metric]
    selected: dict[Metric, FinancialHistoryPoint] = {}
    missing = mismatch = False
    for name in required:
        series = indexed.get(name)
        if series is None or not series.points or series.status == "unavailable":
            missing = True
            continue
        found = next((p for p in series.points if (p.period_start, p.period_end) == period), None)
        if found is None:
            mismatch = True
        else:
            selected[name] = found
    operands = [
        RatioOperand(
            metric=name,
            value=selected[name].value,
            source_snapshot_id=indexed[name].source_snapshot_id,
            source_sha256=indexed[name].source_sha256,
        )
        for name in required
        if name in selected
    ]
    reason: RatioReason | None = None
    values = {name: Decimal(point.value) for name, point in selected.items()}
    if missing:
        reason = "MISSING_INPUT"
    elif mismatch:
        reason = "PERIOD_MISMATCH"
    elif (
        not all(indexed[name].filing_accession for name in required)
        or len({indexed[name].filing_accession for name in required}) != 1
    ):
        reason = "FILING_MISMATCH"
    elif values["revenue"] <= 0:
        reason = "NON_POSITIVE_REVENUE"
    elif "capital_expenditures" in values and values["capital_expenditures"] < 0:
        reason = "NEGATIVE_CAPEX"
    return FinancialRatioPoint(
        metric=metric,
        period_start=period[0],
        period_end=period[1],
        status="available" if reason is None else "unavailable",
        value_percent=_percent(metric, values) if reason is None else None,
        reason=reason,
        available_at=max(indexed[name].available_at for name in required)
        if reason is None
        else None,
        operands=operands,
    )


def _ratios(history: FinancialHistory) -> list[FinancialRatioPoint]:
    indexed = _history_index(history)
    periods = sorted(
        {
            (point.period_start, point.period_end)
            for series in indexed.values()
            for point in series.points
        }
    )[-3:]
    return [_point(metric, period, indexed) for period in periods for metric in _REQUIRED]


class FinancialRatios(Contract):
    report_id: ReportUUID
    revision: Annotated[int, Field(strict=True, ge=1)]
    report_checksum: Sha256
    as_of: Timestamp
    methodology_version: Literal["sec-ratios-v1"] = "sec-ratios-v1"
    history: FinancialHistory
    ratios: Annotated[list[FinancialRatioPoint], Field(max_length=12)]
    limitations: Annotated[list[Text], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def evidence(self) -> Self:
        if (self.report_id, self.revision, self.report_checksum, self.as_of) != (
            self.history.report_id,
            self.history.revision,
            self.history.report_checksum,
            self.history.as_of,
        ):
            raise ValueError("Ratio history identity mismatch")
        if self.ratios != _ratios(self.history):
            raise ValueError("Ratios disagree with archived comparative operands")
        return self


def build_financial_ratios(history: FinancialHistory) -> FinancialRatios:
    checked = FinancialHistory.model_validate(history.model_dump(mode="python"))
    return FinancialRatios(
        report_id=checked.report_id,
        revision=checked.revision,
        report_checksum=checked.report_checksum,
        as_of=checked.as_of,
        history=checked,
        ratios=_ratios(checked),
        limitations=[
            "Wskaźniki opisują dane jednego sprawozdania; mogą obejmować przekształcenia, "
            "nie odtwarzają wiedzy inwestora w dawnym roku.",
            "Marża przepływów po nakładach to (przepływy operacyjne minus nakłady) / przychód. "
            "To ograniczony proxy, nie pełny przepływ dla właścicieli ani wycena.",
            "Brak wskaźnika oznacza brak zgodnych danych, nie zero. "
            "Nie stosujemy progów dobre/złe ani rekomendacji inwestycyjnych.",
        ],
    )

"""Pure deterministic research over frozen packets; no I/O, execution or model calls."""

import hashlib
import json
import math
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from pydantic import TypeAdapter, ValidationError

from alphasense.contracts import AvailableObservation, ResearchInput
from alphasense.instrument_contracts import InstrumentRecord
from alphasense.report_contracts import (
    Finding,
    GitSha,
    ReportContent,
    ReportRevision,
    ReportSection,
    Sha256,
    SourceProvenance,
    seal_report,
)
from alphasense.run_contracts import RunState
from alphasense.snapshot_contracts import SnapshotRecord


class WorkerInputError(ValueError):
    """A deterministic, non-retryable input gate failed; no source text is echoed."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WorkerInputError("INVALID_JSON")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise WorkerInputError("INVALID_JSON")


def _float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise WorkerInputError("INVALID_JSON")
    return parsed


def _context(state: RunState, instrument: InstrumentRecord) -> tuple[RunState, InstrumentRecord]:
    try:
        checked_state = RunState.model_validate(state.model_dump(mode="python"))
        checked_instrument = InstrumentRecord.model_validate(instrument.model_dump(mode="python"))
    except (ValidationError, ValueError, TypeError):
        raise WorkerInputError("INPUT_CONTEXT") from None
    if (
        checked_state.pipeline_version
        not in ("deterministic-research-v1", "sec-fundamentals-v1", "sec-fundamentals-v2")
        or checked_state.instrument_id != checked_instrument.instrument_id
        or checked_state.data_origin != checked_instrument.data_origin
        or checked_state.as_of > checked_state.created_at
    ):
        raise WorkerInputError("INPUT_CONTEXT")
    return checked_state, checked_instrument


def load_input(
    state: RunState,
    instrument: InstrumentRecord,
    snapshots: list[tuple[SnapshotRecord, bytes]],
) -> ResearchInput:
    checked_state, checked_instrument = _context(state, instrument)
    if checked_state.pipeline_version == "sec-fundamentals-v2":
        from alphasense.sec_fundamentals import SecInputError
        from alphasense.sec_fundamentals_v2 import load_sec_input_v2

        try:
            return load_sec_input_v2(checked_state, checked_instrument, snapshots)
        except SecInputError as error:
            raise WorkerInputError(error.code) from None
    if checked_state.pipeline_version == "sec-fundamentals-v1":
        from alphasense.sec_fundamentals import SecInputError, load_sec_input

        try:
            return load_sec_input(checked_state, checked_instrument, snapshots)
        except SecInputError as error:
            raise WorkerInputError(error.code) from None
    supplied = [record.snapshot_id for record, _content in snapshots]
    if len(supplied) != len(set(supplied)) or set(supplied) != set(checked_state.snapshot_ids):
        raise WorkerInputError("SNAPSHOT_SET")
    ordered = {record.snapshot_id: (record, content) for record, content in snapshots}
    observations: list[dict[str, Any]] = []
    for snapshot_id in checked_state.snapshot_ids:
        record, content = ordered[snapshot_id]
        try:
            record = SnapshotRecord.model_validate(record.model_dump(mode="python"))
        except (ValidationError, ValueError, TypeError):
            raise WorkerInputError("INPUT_CONTEXT") from None
        if (
            record.instrument_id != checked_state.instrument_id
            or record.data_origin != checked_state.data_origin
        ):
            raise WorkerInputError("INPUT_IDENTITY")
        if record.media_type != "application/json":
            raise WorkerInputError("SNAPSHOT_FORMAT")
        if (
            not isinstance(content, bytes)
            or len(content) != record.byte_length
            or hashlib.sha256(content).hexdigest() != record.sha256
        ):
            raise WorkerInputError("SNAPSHOT_BYTES")
        if (
            record.available_at is None
            or record.available_at > checked_state.as_of
            or record.as_of > checked_state.as_of
            or record.retrieved_at > checked_state.created_at
        ):
            raise WorkerInputError("INPUT_PIT")
        try:
            packet = ResearchInput.model_validate(
                json.loads(
                    content.decode("utf-8"),
                    object_pairs_hook=_object,
                    parse_constant=_constant,
                    parse_float=_float,
                )
            )
        except WorkerInputError:
            raise
        except (
            UnicodeError,
            json.JSONDecodeError,
            ValidationError,
            ValueError,
            TypeError,
            RecursionError,
        ):
            raise WorkerInputError("INPUT_SCHEMA") from None
        if (
            packet.instrument_id != str(checked_state.instrument_id)
            or packet.asset_type != checked_instrument.asset_type
            or packet.data_origin != checked_state.data_origin
            or packet.as_of != checked_state.as_of
        ):
            raise WorkerInputError("INPUT_IDENTITY")
        for observation in packet.observations:
            if isinstance(observation, AvailableObservation) and (
                observation.source_id != record.source_id
                or observation.snapshot_id != str(record.snapshot_id)
                or observation.available_at < record.available_at
                or observation.available_at > record.retrieved_at
            ):
                raise WorkerInputError("INPUT_PROVENANCE")
            observations.append(observation.model_dump(mode="json"))
    try:
        return ResearchInput.model_validate(
            {
                "schema_version": "1.0",
                "instrument_id": str(checked_state.instrument_id),
                "asset_type": checked_instrument.asset_type,
                "as_of": checked_state.as_of,
                "data_origin": checked_state.data_origin,
                "observations": observations,
            }
        )
    except (ValidationError, ValueError, TypeError):
        raise WorkerInputError("COMBINED_INPUT") from None


def fundamental_section(data: ResearchInput) -> ReportSection:
    checked = ResearchInput.model_validate(data.model_dump(mode="python"))
    metrics = [item for item in checked.observations if item.metric in {"revenue", "net_income"}]
    usable = [
        (index, item)
        for index, item in enumerate(checked.observations)
        if isinstance(item, AvailableObservation)
        and item.metric in {"revenue", "net_income"}
        and item.unit == "currency"
        and item.currency is not None
    ]
    usable.sort(
        key=lambda pair: (pair[1].period_end, pair[1].period_start, pair[1].metric), reverse=True
    )
    findings = [
        Finding(
            kind="fact",
            text=(
                f"{item.metric}={item.value!r} {item.currency}; period "
                f"{item.period_start.isoformat()} to {item.period_end.isoformat()}."
            ),
            observation_indexes=[index],
            method=None,
        )
        for index, item in usable[:40]
    ]
    margin_gap = "Net margin unavailable: missing compatible latest-period inputs."
    if metrics:
        latest = max(item.period_end for item in metrics)
        revenues = [
            (index, item)
            for index, item in usable
            if item.metric == "revenue" and item.period_end == latest
        ]
        earnings = [
            (index, item)
            for index, item in usable
            if item.metric == "net_income" and item.period_end == latest
        ]
        if len(revenues) > 1 or len(earnings) > 1:
            margin_gap = "Net margin unavailable: ambiguous latest-period inputs."
        elif len(revenues) == len(earnings) == 1:
            revenue_index, revenue = revenues[0]
            income_index, income = earnings[0]
            if (revenue.period_start, revenue.currency) != (income.period_start, income.currency):
                margin_gap = "Net margin unavailable: period or currency mismatch."
            elif revenue.value == 0:
                margin_gap = "Net margin unavailable: revenue is zero; no substitute zero ratio."
            else:
                ratio = income.value / revenue.value
                if not math.isfinite(ratio) or (ratio == 0 and income.value != 0):
                    margin_gap = (
                        "Net margin unavailable: result is not representable "
                        "as a finite non-underflowed number."
                    )
                else:
                    findings.append(
                        Finding(
                            kind="calculation",
                            text=(
                                f"net_margin={ratio!r} (ratio); net_income / revenue "
                                f"for period ending {latest.isoformat()}."
                            ),
                            observation_indexes=[income_index, revenue_index],
                            method="ratio-net-margin-v1",
                        )
                    )
                    margin_gap = "Net margin is a limited ratio, not a valuation."
    return ReportSection(
        status="partial" if findings else "blocked",
        findings=findings,
        reason=(
            "Limited deterministic revenue/net_income facts only; "
            f"no DCF, valuation or peers. {margin_gap}"
        ),
    )


def technical_section(data: ResearchInput) -> ReportSection:
    checked = ResearchInput.model_validate(data.model_dump(mode="python"))
    closes = [
        (index, item)
        for index, item in enumerate(checked.observations)
        if isinstance(item, AvailableObservation) and item.metric == "close"
    ]
    reason = (
        "Requires at least three positive available close observations with point periods, "
        "unique times, one known currency and unit=currency_per_unit."
    )
    if (
        len(closes) < 3
        or any(
            item.value <= 0
            or item.period_start != item.period_end
            or item.unit != "currency_per_unit"
            or item.currency is None
            for _, item in closes
        )
        or len({item.currency for _, item in closes}) != 1
        or len({item.period_end for _, item in closes}) != len(closes)
    ):
        return ReportSection(status="blocked", findings=[], reason=reason)
    last = sorted(closes, key=lambda pair: pair[1].period_end)[-3:]
    scale = max(item.value for _, item in last)
    average = scale * (math.fsum(item.value / scale for _, item in last) / 3)
    if not math.isfinite(average) or average <= 0:
        return ReportSection(
            status="blocked",
            findings=[],
            reason="SMA is not representable as a finite positive number.",
        )
    return ReportSection(
        status="partial",
        findings=[
            Finding(
                kind="calculation",
                text=(
                    f"last3_observation_sma={average!r} {last[0][1].currency}/unit; "
                    "last three available point observations only."
                ),
                observation_indexes=[index for index, _item in last],
                method="last3-observation-sma-v1",
            )
        ],
        reason=(
            "Last three observations, not three days; calendar completeness, "
            "signals, backtest and performance are not implemented."
        ),
    )


def compile_report(
    state: RunState,
    instrument: InstrumentRecord,
    snapshots: list[tuple[SnapshotRecord, bytes]],
    git_sha: str,
    implementation_hash: str,
) -> ReportRevision:
    checked_state, checked_instrument = _context(state, instrument)
    data = load_input(checked_state, checked_instrument, snapshots)
    try:
        checked_git = TypeAdapter(GitSha).validate_python(git_sha)
        checked_hash = TypeAdapter(Sha256).validate_python(implementation_hash)
    except (ValidationError, ValueError, TypeError):
        raise WorkerInputError("INPUT_CONTEXT") from None
    by_id = {str(record.snapshot_id): record for record, _content in snapshots}
    pairs = {
        (item.source_id, item.snapshot_id)
        for item in data.observations
        if isinstance(item, AvailableObservation)
    }
    sources = [
        SourceProvenance(
            source_id=source_id,
            snapshot_id=snapshot_id,
            sha256=by_id[snapshot_id].sha256,
            url=by_id[snapshot_id].source_url,
            retrieved_at=by_id[snapshot_id].retrieved_at,
            license=by_id[snapshot_id].license,
        )
        for source_id, snapshot_id in sorted(pairs)
    ]
    fundamental = (
        fundamental_section_v2(data)
        if checked_state.pipeline_version == "sec-fundamentals-v2"
        else fundamental_section(data)
    )
    technical = technical_section(data)
    sec_limitations = []
    if checked_state.pipeline_version in {"sec-fundamentals-v1", "sec-fundamentals-v2"}:
        sec_limitations.append(
            "Availability is conservative local first_seen; "
            "historical availability is not certified. "
            "Reporting periods use UTC-midnight calendar dates; "
            "event_time is SEC acceptanceDateTime."
        )
        sec_limitations.extend(
            f"SEC acceptance evidence snapshot {record.snapshot_id}; SHA256 {record.sha256}."
            for record, _raw in snapshots
            if record.source_id == "sec-edgar-submissions-v1"
        )
    try:
        return seal_report(
            ReportContent(
                schema_version="1.0",
                report_id=uuid5(
                    NAMESPACE_URL, "alphasense:worker-report:" + str(checked_state.run_id)
                ),
                revision_id=uuid5(
                    NAMESPACE_URL, "alphasense:worker-revision:" + str(checked_state.run_id)
                ),
                parent_revision_id=None,
                revision=1,
                generated_at_utc=checked_state.created_at,
                input=data,
                status="partial" if fundamental.findings or technical.findings else "blocked",
                methodology_version=checked_state.pipeline_version + ":" + checked_hash[:16],
                pipeline_git_sha=checked_git,
                sources=sources,
                fundamental_section=fundamental,
                technical_section=technical,
                synthesis_section=ReportSection(
                    status="blocked",
                    findings=[],
                    reason="No synthesis engine or LLM invocation in this pipeline.",
                ),
                scenario_section=ReportSection(
                    status="not_applicable",
                    findings=[],
                    reason="Scenario modelling is not implemented by this limited pipeline.",
                ),
                uncertainties=[
                    "Input metadata and source claims are declarations; "
                    "authenticity and licensing are not certified."
                ],
                limitations=[
                    "Implementation SHA256: " + checked_hash,
                    "Limited revenue/net_income facts and last-three-observation SMA only; "
                    "no full fundamental or technical research.",
                    "No data fetching during worker analysis, LLM, valuation, scenarios, "
                    "calendar completeness, "
                    "buy/sell signals or execution.",
                    *sec_limitations,
                ],
                disclaimer="Research only. No order execution or personalized investment advice.",
                model_provenance=None,
                prompt_template_version=None,
                chart_artifact_ids=[],
            )
        )
    except (ValidationError, ValueError, TypeError):
        raise WorkerInputError("INPUT_PROVENANCE") from None


def fundamental_section_v2(data: ResearchInput) -> ReportSection:
    checked = ResearchInput.model_validate(data.model_dump(mode="python"))
    base = fundamental_section(checked)
    findings = list(base.findings)
    extra = {
        "cash_and_equivalents",
        "long_term_debt_current",
        "long_term_debt_noncurrent",
        "operating_cash_flow",
        "capital_expenditures",
    }
    usable = [
        (i, o)
        for i, o in enumerate(checked.observations)
        if isinstance(o, AvailableObservation)
        and o.metric in extra
        and o.unit == "currency"
        and o.currency == "USD"
    ]
    for index, item in usable:
        findings.append(
            Finding(
                kind="fact",
                text=(
                    f"{item.metric}={item.value!r} USD; period "
                    f"{item.period_start.isoformat()} to {item.period_end.isoformat()}."
                ),
                observation_indexes=[index],
                method=None,
            )
        )
    cashflow = [(i, o) for i, o in usable if o.metric == "operating_cash_flow"]
    capex = [(i, o) for i, o in usable if o.metric == "capital_expenditures"]
    if len(cashflow) == len(capex) == 1:
        ci, c = cashflow[0]
        pi, p = capex[0]
        if (
            (c.period_start, c.period_end, c.currency) == (p.period_start, p.period_end, p.currency)
            and c.period_start < c.period_end
            and p.value >= 0
        ):
            value = c.value - p.value
            if math.isfinite(value):
                findings.append(
                    Finding(
                        kind="calculation",
                        text=(
                            f"free_cash_flow={value!r} USD; "
                            "operating_cash_flow - capital_expenditures."
                        ),
                        observation_indexes=[ci, pi],
                        method="free-cash-flow-v1",
                    )
                )
    return ReportSection(
        status="partial" if findings else "blocked",
        findings=findings,
        reason=(
            "Limited annual facts and OCF minus capex; cash is a point balance. "
            "Debt observations are current/noncurrent portions of long-term debt, "
            "not total borrowing. No DCF, valuation or peers."
        ),
    )

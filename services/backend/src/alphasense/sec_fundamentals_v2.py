"""Expanded annual SEC observations over eight immutable responses."""

import hashlib
from typing import Any

from alphasense.contracts import ResearchInput
from alphasense.instrument_contracts import InstrumentRecord
from alphasense.run_contracts import RunState
from alphasense.sec_contracts import SEC_SOURCE_IDS
from alphasense.sec_fundamentals import (
    SecInputError,
    _cik,
    _date,
    _facts,
    _filing,
    _json,
    _midnight,
    _number,
    load_sec_input,
)
from alphasense.snapshot_contracts import SnapshotRecord

EXTRA = {
    "cash": ("cash_and_equivalents", "CashAndCashEquivalentsAtCarryingValue", True),
    "debt_current": ("long_term_debt_current", "LongTermDebtCurrent", True),
    "debt_noncurrent": ("long_term_debt_noncurrent", "LongTermDebtNoncurrent", True),
    "operating_cf": ("operating_cash_flow", "NetCashProvidedByUsedInOperatingActivities", False),
    "capex": ("capital_expenditures", "PaymentsToAcquirePropertyPlantAndEquipment", False),
}


def load_sec_input_v2(
    state: RunState, instrument: InstrumentRecord, snapshots: list[tuple[SnapshotRecord, bytes]]
) -> ResearchInput:
    if (
        state.pipeline_version != "sec-fundamentals-v2"
        or len(snapshots) != 8
        or len(state.snapshot_ids) != 8
    ):
        raise SecInputError("SEC_SNAPSHOT_SET")
    if len({r.snapshot_id for r, _ in snapshots}) != 8 or set(state.snapshot_ids) != {
        r.snapshot_id for r, _ in snapshots
    }:
        raise SecInputError("SEC_SNAPSHOT_SET")
    base_roles = {SEC_SOURCE_IDS[k] for k in ("submissions", "revenue", "net_income")}
    original = [(r, b) for r, b in snapshots if r.source_id in base_roles]
    base_state = state.model_copy(
        update={
            "pipeline_version": "sec-fundamentals-v1",
            "snapshot_ids": [r.snapshot_id for r, _ in original],
        }
    )
    base = load_sec_input(base_state, instrument, original)
    submissions = next((r, b) for r, b in original if r.source_id == SEC_SOURCE_IDS["submissions"])
    cik = _cik(_json(submissions[1]).get("cik"))
    filing = _filing(_json(submissions[1]), cik, instrument, submissions[0].retrieved_at)
    start, end = base.observations[0].period_start, base.observations[0].period_end
    observations: list[Any] = list(base.observations)
    for role, (metric, tag, instant) in EXTRA.items():
        matching = [(r, b) for r, b in snapshots if r.source_id == SEC_SOURCE_IDS[role]]
        if len(matching) != 1:
            raise SecInputError("SEC_SNAPSHOT_SET")
        record, raw = matching[0]
        if (
            record.instrument_id != state.instrument_id
            or record.data_origin != state.data_origin
            or record.media_type != "application/json"
            or len(raw) != record.byte_length
            or hashlib.sha256(raw).hexdigest() != record.sha256
            or str(record.source_url)
            != f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"
        ):
            raise SecInputError("SEC_INPUT_IDENTITY")
        if (
            record.available_at != record.retrieved_at
            or record.retrieved_at > state.as_of
            or record.as_of > state.as_of
            or record.retrieved_at < filing.accepted_at
        ):
            raise SecInputError("SEC_PIT")
        payload = _json(raw)
        value = None
        if instant:
            if (
                _cik(payload.get("cik")) != cik
                or payload.get("taxonomy") != "us-gaap"
                or payload.get("tag") != tag
            ):
                raise SecInputError("SEC_CONCEPT_MISMATCH")
            units = payload.get("units")
            if not isinstance(units, dict) or not isinstance(units.get("USD"), list):
                raise SecInputError("SEC_UNIT_UNSUPPORTED")
            candidates = set()
            for row in units["USD"]:
                if not isinstance(row, dict):
                    raise SecInputError("SEC_FACT_SCHEMA")
                if row.get("accn") != filing.accession:
                    continue
                if row.get("form") != "10-K" or _date(row.get("filed")) != filing.filing_date:
                    raise SecInputError("SEC_FACT_CONTEXT")
                if _date(row.get("end")) != filing.report_date:
                    continue
                if "start" in row or row.get("fp") != "FY":
                    raise SecInputError("SEC_FACT_CONTEXT")
                candidates.add(_number(row.get("val"))[1])
            if len(candidates) > 1:
                raise SecInputError("SEC_FACT_AMBIGUOUS")
            value = next(iter(candidates), None)
        else:
            fact = _facts(payload, cik, tag, filing)
            if fact is not None:
                if (_midnight(fact[0]), _midnight(fact[1])) != (start, end):
                    raise SecInputError("SEC_PERIOD_AMBIGUOUS")
                value = fact[2]
        observation: dict[str, Any] = dict(
            metric=metric,
            unit="currency",
            currency="USD",
            period_start=end if instant else start,
            period_end=end,
        )
        if value is None:
            observation.update(
                status="missing",
                value=None,
                reason="No matching USD fact for the latest accepted annual filing",
            )
        else:
            observation.update(
                status="available",
                value=value,
                source_id=record.source_id,
                snapshot_id=str(record.snapshot_id),
                event_time=filing.accepted_at,
                available_at=record.retrieved_at,
            )
        observations.append(observation)
    return ResearchInput.model_validate(
        {**base.model_dump(mode="python"), "observations": observations}
    )

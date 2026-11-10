"""Expanded SEC parser uses synthetic annual/instant facts only."""

from copy import deepcopy

import pytest
from test_sec_fundamentals import bundle, payloads

from alphasense.sec_fundamentals import SecInputError
from alphasense.sec_fundamentals_v2 import EXTRA, load_sec_input_v2
from alphasense.worker_engine import fundamental_section_v2


def expanded():
    data = payloads()
    for role, (_metric, tag, instant) in EXTRA.items():
        value = deepcopy(data["net_income"])
        value["tag"] = tag
        value["units"]["USD"][0]["val"] = 10 if role == "capex" else 40
        if instant:
            del value["units"]["USD"][0]["start"]
        data[role] = value
    return data


def load(data=None):
    state, identity, snapshots = bundle(expanded() if data is None else data)
    return load_sec_input_v2(
        state.model_copy(update={"pipeline_version": "sec-fundamentals-v2"}), identity, snapshots
    )


def test_expanded_facts_instant_and_fcf():
    data = load()
    assert len(data.observations) == 7
    cash = next(o for o in data.observations if o.metric == "cash_and_equivalents")
    assert cash.period_start == cash.period_end
    result = fundamental_section_v2(data)
    assert any(
        "free_cash_flow=30.0" in f.text and len(f.observation_indexes) == 2 for f in result.findings
    )


@pytest.mark.parametrize(
    "change,code",
    [
        ("value", "SEC_VALUE"),
        ("conflict", "SEC_FACT_AMBIGUOUS"),
        ("period", "SEC_PERIOD_AMBIGUOUS"),
        ("identity", "SEC_CONCEPT_MISMATCH"),
    ],
)
def test_expanded_gates(change, code):
    data = expanded()
    role = "operating_cf" if change == "period" else "cash"
    concept = data[role]
    row = concept["units"]["USD"][0]
    if change == "value":
        row["val"] = True
    elif change == "conflict":
        concept["units"]["USD"].append({**row, "val": 999})
    elif change == "period":
        row["start"] = "2022-12-31"
    else:
        concept["tag"] = "Wrong"
    with pytest.raises(SecInputError, match=code):
        load(data)


def test_absent_optional_fact_is_missing_not_zero():
    data = expanded()
    data["capex"]["units"]["USD"] = []
    result = load(data)
    missing = next(o for o in result.observations if o.metric == "capital_expenditures")
    assert missing.status == "missing" and missing.value is None
    assert not any("free_cash_flow=" in f.text for f in fundamental_section_v2(result).findings)


def test_negative_capex_does_not_create_fcf():
    data = expanded()
    data["capex"]["units"]["USD"][0]["val"] = -1
    assert not any("free_cash_flow=" in f.text for f in fundamental_section_v2(load(data)).findings)


def test_instant_prior_comparative_is_not_selected():
    data = expanded()
    row = data["cash"]["units"]["USD"][0]
    data["cash"]["units"]["USD"].append({**row, "end": "2022-12-31", "val": 900})
    assert (
        next(o for o in load(data).observations if o.metric == "cash_and_equivalents").value == 40
    )


def test_extra_snapshot_duplicates_are_rejected():
    state, identity, snapshots = bundle(expanded())
    state = state.model_copy(update={"pipeline_version": "sec-fundamentals-v2"})
    snapshots[-1] = snapshots[-2]
    with pytest.raises(SecInputError, match="SEC_SNAPSHOT_SET"):
        load_sec_input_v2(state, identity, snapshots)


def test_extra_snapshot_future_is_rejected():
    from datetime import timedelta

    state, identity, snapshots = bundle(expanded())
    state = state.model_copy(update={"pipeline_version": "sec-fundamentals-v2"})
    record, raw = snapshots[-1]
    snapshots[-1] = (
        record.model_copy(update={"retrieved_at": state.as_of + timedelta(days=1)}),
        raw,
    )
    with pytest.raises(SecInputError, match="SEC_PIT"):
        load_sec_input_v2(state, identity, snapshots)

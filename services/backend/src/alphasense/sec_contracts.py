"""Bounded SEC read-only resource identities. No user-supplied network URLs."""

from typing import Annotated, Literal

from pydantic import AfterValidator, Field, StringConstraints

from alphasense.contracts import Contract
from alphasense.instrument_contracts import Symbol
from alphasense.report_contracts import ReportUUID


def nonzero_cik(value: str) -> str:
    if value == "0000000000":
        raise ValueError("CIK must identify a filer")
    return value


CIK = Annotated[
    str,
    StringConstraints(strict=True, min_length=10, max_length=10, pattern=r"^[0-9]{10}$"),
    AfterValidator(nonzero_cik),
    Field(json_schema_extra={"not": {"enum": ["0000000000"]}}),
]
RevenueConcept = Literal[
    "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"
]
SEC_PROVIDER_ID = "sec-edgar-public-v1"
SEC_PIPELINE: Literal["sec-fundamentals-v1"] = "sec-fundamentals-v1"
SEC_PIPELINE_V2: Literal["sec-fundamentals-v2"] = "sec-fundamentals-v2"
SEC_CONCEPTS = {
    "net_income": "NetIncomeLoss",
    "cash": "CashAndCashEquivalentsAtCarryingValue",
    "debt_current": "LongTermDebtCurrent",
    "debt_noncurrent": "LongTermDebtNoncurrent",
    "operating_cf": "NetCashProvidedByUsedInOperatingActivities",
    "capex": "PaymentsToAcquirePropertyPlantAndEquipment",
}
SEC_ROLES_V1 = ("submissions", "revenue", "net_income")
SEC_ROLES_V2 = (*SEC_ROLES_V1, "cash", "debt_current", "debt_noncurrent", "operating_cf", "capex")
SEC_LICENSE = "SEC website dissemination policy; https://www.sec.gov/about/privacy-information"
SEC_SOURCE_IDS = {
    "submissions": "sec-edgar-submissions-v1",
    "revenue": "sec-edgar-revenue-v1",
    "net_income": "sec-edgar-net-income-v1",
}
SEC_SOURCE_IDS.update(
    {role: f"sec-edgar-{role}-v2" for role in SEC_ROLES_V2 if role not in SEC_SOURCE_IDS}
)


class SecFetchRequest(Contract):
    cik: CIK
    resource: Literal[
        "submissions",
        "revenue",
        "net_income",
        "cash",
        "debt_current",
        "debt_noncurrent",
        "operating_cf",
        "capex",
    ]
    revenue_concept: RevenueConcept = "RevenueFromContractWithCustomerExcludingAssessedTax"


class SecImportRequest(Contract):
    cik: CIK
    symbol: Symbol
    exchange_mic: Literal["XNAS", "XNYS"]
    instrument_id: ReportUUID
    run_id: ReportUUID
    revenue_concept: RevenueConcept = "RevenueFromContractWithCustomerExcludingAssessedTax"
    pipeline_version: Literal["sec-fundamentals-v1", "sec-fundamentals-v2"] = SEC_PIPELINE
    refresh: bool = Field(default=False, strict=True)


def sec_url(request: SecFetchRequest) -> str:
    checked = SecFetchRequest.model_validate(request.model_dump())
    if checked.cik == "0000000000":
        raise ValueError("CIK must identify a filer")
    if checked.resource == "submissions":
        return f"https://data.sec.gov/submissions/CIK{checked.cik}.json"
    concept = (
        checked.revenue_concept if checked.resource == "revenue" else SEC_CONCEPTS[checked.resource]
    )
    return f"https://data.sec.gov/api/xbrl/companyconcept/CIK{checked.cik}/us-gaap/{concept}.json"

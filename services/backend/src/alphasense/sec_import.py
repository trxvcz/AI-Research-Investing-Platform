"""Explicit SEC ingestion with immutable raw cache. No scheduler or paid fallback."""

import argparse
import base64
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import AnyHttpUrl, ValidationError
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from alphasense.db import StoreUnavailable, get_store
from alphasense.instrument_contracts import InstrumentCreate, InstrumentRecord
from alphasense.instruments import InstrumentConflict, InstrumentNotFound, InstrumentStore
from alphasense.provider_contracts import ProviderPolicy
from alphasense.provider_policy import FreeOnlyGateway, ProviderDenied, _admit, load_policy
from alphasense.provider_quota import QuotaStore
from alphasense.run_contracts import RunCreate, RunState
from alphasense.runs import ResearchStore, RunConflict, RunNotFound
from alphasense.sec_contracts import (
    SEC_LICENSE,
    SEC_PIPELINE,
    SEC_PIPELINE_V2,
    SEC_PROVIDER_ID,
    SEC_ROLES_V1,
    SEC_ROLES_V2,
    SEC_SOURCE_IDS,
    SecFetchRequest,
    SecImportRequest,
    sec_url,
)
from alphasense.sec_fundamentals import SecInputError, load_sec_input, parse_sec_submissions
from alphasense.sec_receipts import SecReceiptStore
from alphasense.sec_transport import SecResponse, SecTransport, SecTransportError
from alphasense.snapshot_contracts import SnapshotCreate, SnapshotRecord
from alphasense.snapshots import SnapshotStore


@dataclass(frozen=True)
class _FetchFailure:
    code: str


class SecImporter:
    def __init__(
        self,
        engine: Engine,
        policy: ProviderPolicy,
        transport: Callable[[object], SecResponse],
    ) -> None:
        self.engine = engine
        self.policy = ProviderPolicy.model_validate(policy.model_dump(mode="python"))
        self.transport = transport
        self.archive = SnapshotStore(engine)
        self.receipts = SecReceiptStore(engine)
        self.gateway = FreeOnlyGateway(
            self.policy, {SEC_PROVIDER_ID: self._paced_fetch}, QuotaStore(engine)
        )

    def _paced_fetch(self, payload: object) -> SecResponse | _FetchFailure:
        try:
            with self.engine.begin() as connection:
                acquired = connection.scalar(
                    text(
                        "SELECT pg_try_advisory_xact_lock(hashtextextended('sec-edgar-rate-v1',0))"
                    )
                )
                if not acquired:
                    raise ProviderDenied("SEC_RATE_BUSY")
                now = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
                grant = next(
                    item for item in self.policy.providers if item.provider_id == SEC_PROVIDER_ID
                )
                _admit(grant, "public", now)
                try:
                    return self.transport(payload)
                except SecTransportError as error:
                    return _FetchFailure(error.code)
                finally:
                    # One in-flight request and >=1 second after completion, shared by
                    # application processes using this DB; quota was already committed.
                    time.sleep(1)
        except SQLAlchemyError:
            raise StoreUnavailable("SEC request pacing unavailable") from None

    def _cached(
        self, request: SecImportRequest, resource: SecFetchRequest
    ) -> SnapshotRecord | None:
        return self.receipts.find(request.instrument_id, sec_url(resource))

    def _fetch(self, resource: SecFetchRequest) -> SecResponse:
        result = self.gateway.invoke(SEC_PROVIDER_ID, resource, classification="public")
        if isinstance(result, _FetchFailure):
            raise SecTransportError(result.code)
        return result

    def _archive(
        self, request: SecImportRequest, resource: SecFetchRequest, response: SecResponse
    ) -> SnapshotRecord:
        url = sec_url(resource)
        if response.url != url:
            raise SecInputError("SEC_RESPONSE_IDENTITY")
        digest = hashlib.sha256(response.content).hexdigest()
        known = self.receipts.find(request.instrument_id, url, digest)
        if known is not None:
            return known
        written = self.archive.create(
            SnapshotCreate(
                schema_version="1.0",
                snapshot_id=uuid4(),
                instrument_id=request.instrument_id,
                data_origin="live",
                source_id=SEC_SOURCE_IDS[resource.resource],
                source_url=AnyHttpUrl(url),
                license=SEC_LICENSE,
                as_of=response.retrieved_at,
                available_at=response.retrieved_at,
                retrieved_at=response.retrieved_at,
                media_type="application/json",
                sha256=digest,
                byte_length=len(response.content),
                content_base64=base64.b64encode(response.content).decode("ascii"),
            )
        )
        record = SnapshotRecord.model_validate(written.model_dump(exclude={"created"}))
        return self.receipts.record(record, resource)

    def _instrument(self, request: SecImportRequest, response: SecResponse) -> InstrumentRecord:
        document = parse_sec_submissions(response.content, request.cik)
        tickers, exchanges = document.get("tickers"), document.get("exchanges")
        expected = "Nasdaq" if request.exchange_mic == "XNAS" else "NYSE"
        if (
            not isinstance(tickers, list)
            or not isinstance(exchanges, list)
            or len(tickers) != len(exchanges)
            or (request.symbol, expected) not in list(zip(tickers, exchanges, strict=True))
            or not isinstance(document.get("name"), str)
        ):
            raise SecInputError("SEC_LISTING_IDENTITY")
        store = InstrumentStore(self.engine)
        try:
            existing = store.get(request.instrument_id)
            if (
                existing.symbol != request.symbol
                or existing.exchange_mic != request.exchange_mic
                or existing.currency != "USD"
                or existing.asset_type != "equity"
                or existing.data_origin != "live"
                or str(existing.source_url) != response.url
            ):
                raise SecInputError("SEC_INSTRUMENT_CONFLICT")
            return existing
        except InstrumentNotFound:
            written = store.create(
                InstrumentCreate(
                    schema_version="1.0",
                    instrument_id=request.instrument_id,
                    symbol=request.symbol,
                    exchange_mic=request.exchange_mic,
                    currency="USD",
                    display_name=document["name"],
                    asset_type="equity",
                    data_origin="live",
                    as_of=response.retrieved_at,
                    available_at=response.retrieved_at,
                    source_id=SEC_SOURCE_IDS["submissions"],
                    source_url=AnyHttpUrl(response.url),
                    license=SEC_LICENSE,
                )
            )
            return InstrumentRecord.model_validate(written.model_dump(exclude={"created"}))

    def import_run(self, data: SecImportRequest) -> RunState:
        request = SecImportRequest.model_validate(data.model_dump(mode="python"))
        roles = SEC_ROLES_V2 if request.pipeline_version == SEC_PIPELINE_V2 else SEC_ROLES_V1
        if request.pipeline_version == SEC_PIPELINE_V2:
            from alphasense.sec_fundamentals_v2 import load_sec_input_v2 as validate_input
        else:
            validate_input = load_sec_input
        try:
            existing = ResearchStore(self.engine).get(request.run_id)
        except RunNotFound:
            existing = None
        if existing is not None:
            if (
                existing.instrument_id != request.instrument_id
                or existing.pipeline_version != request.pipeline_version
            ):
                raise RunConflict("SEC immutable run identity conflict")
            identity = InstrumentStore(self.engine).get(request.instrument_id)
            expected = {
                SEC_SOURCE_IDS[role]: sec_url(
                    SecFetchRequest.model_validate(
                        dict(
                            cik=request.cik, resource=role, revenue_concept=request.revenue_concept
                        )
                    )
                )
                for role in roles
            }
            snapshots = [self.archive.content(key) for key in existing.snapshot_ids]
            if (
                existing.instrument_id != request.instrument_id
                or existing.pipeline_version != request.pipeline_version
                or identity.symbol != request.symbol
                or identity.exchange_mic != request.exchange_mic
                or len(snapshots) != len(roles)
                or {record.source_id: str(record.source_url) for record, _raw in snapshots}
                != expected
            ):
                raise RunConflict("SEC immutable run identity conflict")
            validate_input(existing, identity, snapshots)
            return existing
        resources = [
            SecFetchRequest.model_validate(
                dict(cik=request.cik, resource=role, revenue_concept=request.revenue_concept)
            )
            for role in roles
        ]
        records: list[SnapshotRecord] = []
        instrument: InstrumentRecord | None = None
        for resource in resources:
            cached = None if request.refresh else self._cached(request, resource)
            if cached is not None:
                record, content = self.archive.content(cached.snapshot_id)
                response = SecResponse(sec_url(resource), content, record.retrieved_at)
            else:
                response = self._fetch(resource)
            if resource.resource == "submissions":
                instrument = self._instrument(request, response)
            records.append(cached or self._archive(request, resource, response))
        assert instrument is not None
        cutoff = max(record.retrieved_at for record in records)
        definition = RunCreate(
            schema_version="1.0",
            run_id=request.run_id,
            instrument_id=request.instrument_id,
            as_of=cutoff,
            snapshot_ids=[record.snapshot_id for record in records],
            pipeline_version=request.pipeline_version,
        )
        # Validate all financial context before creating a queued run. Raw bytes remain
        # archived if parsing fails; a later retry never rewrites these originals.
        now = datetime.now(UTC)
        provisional = RunState(
            **definition.model_dump(exclude={"action", "schema_version"}),
            data_origin="live",
            sequence=1,
            status="queued",
            current_step="data",
            completed_steps=[],
            error_code=None,
            error_reason=None,
            report_revision_id=None,
            report_status=None,
            created_at=now,
            updated_at=now,
        )
        validate_input(
            provisional,
            instrument,
            [self.archive.content(record.snapshot_id) for record in records],
        )
        result = ResearchStore(self.engine).create(definition)
        return RunState.model_validate(result.model_dump(exclude={"created"}))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cik", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--mic", choices=("XNAS", "XNYS"), required=True)
    parser.add_argument("--instrument-id", type=UUID)
    parser.add_argument("--run-id", type=UUID)
    parser.add_argument(
        "--revenue-concept",
        default="RevenueFromContractWithCustomerExcludingAssessedTax",
        choices=(
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
        ),
    )
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--pipeline", choices=(SEC_PIPELINE, SEC_PIPELINE_V2), default=SEC_PIPELINE)
    args = parser.parse_args(argv)
    try:
        user_agent = os.environ.get("ALPHASENSE_SEC_USER_AGENT", "")
        transport = SecTransport(user_agent)
        request = SecImportRequest(
            cik=args.cik,
            symbol=args.symbol,
            exchange_mic=args.mic,
            instrument_id=args.instrument_id
            or uuid5(NAMESPACE_URL, f"alphasense:sec-listing:{args.cik}:{args.mic}:{args.symbol}"),
            run_id=args.run_id or uuid4(),
            revenue_concept=args.revenue_concept,
            refresh=args.refresh,
            pipeline_version=args.pipeline,
        )
        store = get_store()
        store.check_ready()
        result = SecImporter(store.engine, load_policy(), transport).import_run(request)
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False))
        return 0
    except (ProviderDenied, SecInputError, SecTransportError) as error:
        print(f"SEC import blocked: {error.code}", file=sys.stderr)
        return 1
    except (StoreUnavailable, InstrumentConflict, RunConflict, ValidationError, ValueError):
        print("SEC import blocked: invalid configuration, identity or storage", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""SEC importer integration over synthetic responses and isolated real PostgreSQL.

The importer exercises its live-data code path; every response is a generated fixture,
never a downloaded company statement, and no network operation is performed.
"""

import base64
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, select
from test_runs import database as database
from test_sec_fundamentals import CIK, payloads

from alphasense.db import ReportStore
from alphasense.db_schema import (
    instruments,
    provider_quota_windows,
    raw_snapshots,
    report_revisions,
    research_runs,
)
from alphasense.instruments import InstrumentStore
from alphasense.provider_contracts import ProviderGrant, ProviderPolicy
from alphasense.run_contracts import RunCreate
from alphasense.runs import ResearchStore, RunConflict
from alphasense.sec_contracts import (
    SEC_LICENSE,
    SEC_PIPELINE,
    SEC_PROVIDER_ID,
    SEC_ROLES_V1,
    SEC_SOURCE_IDS,
    SecFetchRequest,
    SecImportRequest,
    sec_url,
)
from alphasense.sec_fundamentals import SecInputError
from alphasense.sec_import import SecImporter
from alphasense.sec_transport import SecResponse, SecTransportError
from alphasense.snapshot_contracts import SnapshotCreate
from alphasense.snapshots import SnapshotStore
from alphasense.worker import current_git_sha, implementation_fingerprint, process_once

pytestmark = pytest.mark.postgres


@pytest.fixture(autouse=True)
def no_network_pacing_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    from alphasense import sec_import

    # The DB advisory lock is real. Sleeping is unnecessary for synthetic callbacks.
    monkeypatch.setattr(sec_import.time, "sleep", lambda _seconds: None)


def configured_policy(*, quota_limit: int = 20) -> ProviderPolicy:
    now = datetime.now(UTC)
    approved = ProviderGrant(
        provider_id=SEC_PROVIDER_ID,
        enabled=True,
        capability="data",
        execution="remote",
        billing="free_no_billing",
        max_charge_usd=0,
        paid_fallback=False,
        hard_cap_verified=True,
        quality_pass=True,
        terms_url="https://example.invalid/synthetic-sec-review",
        terms_sha256=hashlib.sha256(b"Generated review fixture, not actual SEC terms").hexdigest(),
        reviewed_at=now - timedelta(hours=1),
        review_expires_at=now + timedelta(hours=1),
        data_policy="public_only",
        quota_scope="synthetic-sec-test-" + uuid4().hex,
        quota_limit=quota_limit,
        quota_window_start=now - timedelta(hours=1),
        quota_window_end=now + timedelta(hours=1),
    )
    return ProviderPolicy(schema_version="1.0", policy="free-only-v1", providers=(approved,))


def request(**changes: Any) -> SecImportRequest:
    return SecImportRequest.model_validate(
        {
            "cik": CIK,
            "symbol": "SYNTH-SEC",
            "exchange_mic": "XNAS",
            "instrument_id": uuid4(),
            "run_id": uuid4(),
            **changes,
        }
    )


class SyntheticTransport:
    def __init__(self, values: dict[str, dict[str, Any]] | None = None) -> None:
        self.values = deepcopy(values if values is not None else payloads())
        self.calls: list[SecFetchRequest] = []

    def content(self, role: str) -> bytes:
        return json.dumps(self.values[role], ensure_ascii=False, indent=2).encode("utf-8") + b"\n"

    def __call__(self, value: object) -> SecResponse:
        assert isinstance(value, SecFetchRequest)
        checked = SecFetchRequest.model_validate(value.model_dump())
        self.calls.append(checked)
        return SecResponse(sec_url(checked), self.content(checked.resource), datetime.now(UTC))


def used(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.scalar(select(func.coalesce(func.sum(provider_quota_windows.c.used), 0)))
        )


def count(engine: Engine, table: Any) -> int:
    with engine.connect() as connection:
        return int(connection.scalar(select(func.count()).select_from(table)))


def test_import_archives_exact_bytes_and_worker_produces_limited_report(database: Engine) -> None:
    transport = SyntheticTransport()
    target = request()
    state = SecImporter(database, configured_policy(), transport).import_run(target)
    assert state.status == "queued" and state.pipeline_version == SEC_PIPELINE
    assert state.data_origin == "live" and state.instrument_id == target.instrument_id
    assert len(transport.calls) == 3 and used(database) == 3
    assert count(database, raw_snapshots) == 3 and count(database, instruments) == 1
    archive = SnapshotStore(database)
    for snapshot_id in state.snapshot_ids:
        record, content = archive.content(snapshot_id)
        role = next(role for role, source in SEC_SOURCE_IDS.items() if source == record.source_id)
        assert content == transport.content(role)
        assert record.sha256 == hashlib.sha256(content).hexdigest()
        assert record.available_at == record.retrieved_at
        assert record.as_of == record.retrieved_at <= state.as_of
    identity = InstrumentStore(database).get(target.instrument_id)
    assert identity.symbol == target.symbol and identity.exchange_mic == "XNAS"
    assert identity.data_origin == "live" and identity.currency == "USD"
    assert process_once(
        database, "synthetic-sec-worker", current_git_sha(), implementation_fingerprint()
    )
    final = ResearchStore(database).get(target.run_id)
    assert final.status == "completed" and final.report_status == "partial"
    with database.connect() as connection:
        report_id = connection.scalar(select(report_revisions.c.report_id))
    report = ReportStore(database).get_report(report_id)
    assert report.input.observations[0].value == 100
    assert report.input.observations[1].value == 25
    assert "net_margin=0.25" in report.fundamental_section.findings[-1].text
    assert report.technical_section.status == "blocked"
    assert len(report.sources) == 2 and report.model_provenance is None


def test_same_run_retry_and_new_run_use_cache_without_new_quota(database: Engine) -> None:
    transport = SyntheticTransport()
    policy = configured_policy()
    target = request()
    first = SecImporter(database, policy, transport).import_run(target)
    archive = SnapshotStore(database)
    before = [archive.content(snapshot_id) for snapshot_id in first.snapshot_ids]
    replacement = SecImporter(database, policy, transport)
    assert replacement.import_run(target) == first
    another = replacement.import_run(target.model_copy(update={"run_id": uuid4()}))
    assert another.snapshot_ids == first.snapshot_ids and another.as_of == first.as_of
    assert len(transport.calls) == 3 and used(database) == 3
    assert count(database, raw_snapshots) == 3 and count(database, research_runs) == 2
    assert [archive.content(snapshot_id) for snapshot_id in first.snapshot_ids] == before


def test_refresh_same_bytes_keeps_first_seen_and_changed_bytes_preserve_old_archive(
    database: Engine,
) -> None:
    transport = SyntheticTransport()
    importer = SecImporter(database, configured_policy(), transport)
    target = request()
    first = importer.import_run(target)
    archive = SnapshotStore(database)
    original = {snapshot_id: archive.content(snapshot_id) for snapshot_id in first.snapshot_ids}
    refreshed = importer.import_run(target.model_copy(update={"run_id": uuid4(), "refresh": True}))
    assert refreshed.snapshot_ids == first.snapshot_ids and refreshed.as_of == first.as_of
    assert len(transport.calls) == 6 and used(database) == 6
    assert count(database, raw_snapshots) == 3
    transport.values["net_income"]["units"]["USD"][0]["val"] = 30
    changed = importer.import_run(target.model_copy(update={"run_id": uuid4(), "refresh": True}))
    assert changed.snapshot_ids[:2] == first.snapshot_ids[:2]
    assert changed.snapshot_ids[2] != first.snapshot_ids[2]
    assert count(database, raw_snapshots) == 4 and used(database) == 9
    assert {
        snapshot_id: archive.content(snapshot_id) for snapshot_id in first.snapshot_ids
    } == original
    assert ResearchStore(database).get(target.run_id).snapshot_ids == first.snapshot_ids


def test_retry_old_run_after_refresh_keeps_original_frozen_inputs_and_spends_nothing(
    database: Engine,
) -> None:
    transport = SyntheticTransport()
    importer = SecImporter(database, configured_policy(), transport)
    target = request()
    original = importer.import_run(target)
    transport.values["net_income"]["units"]["USD"][0]["val"] = 30
    newer = importer.import_run(target.model_copy(update={"run_id": uuid4(), "refresh": True}))
    assert newer.snapshot_ids != original.snapshot_ids
    calls_before, quota_before = len(transport.calls), used(database)
    retried = importer.import_run(target)
    assert retried == original
    assert len(transport.calls) == calls_before and used(database) == quota_before


@pytest.mark.parametrize(
    "change",
    [
        {"instrument_id": "942d0a13-11bf-4b8f-91af-6c12d748e629"},
        {"symbol": "OTHER-SEC"},
        {"cik": "0000000456"},
    ],
)
def test_retry_cannot_rebind_existing_run_to_changed_request(
    database: Engine, change: dict[str, str]
) -> None:
    transport = SyntheticTransport()
    importer = SecImporter(database, configured_policy(), transport)
    target = request()
    first = importer.import_run(target)
    altered = SecImportRequest.model_validate({**target.model_dump(), **change})
    with pytest.raises(RunConflict):
        importer.import_run(altered)
    assert ResearchStore(database).get(target.run_id) == first
    assert len(transport.calls) == 3 and used(database) == 3


@pytest.mark.parametrize("mismatch", ["cik", "listing"])
def test_wrong_identity_does_not_create_instrument_or_run(database: Engine, mismatch: str) -> None:
    values = payloads()
    if mismatch == "cik":
        values["submissions"]["cik"] = "0000000456"
    else:
        values["submissions"]["tickers"] = ["OTHER-SEC"]
    transport = SyntheticTransport(values)
    with pytest.raises(SecInputError):
        SecImporter(database, configured_policy(), transport).import_run(request())
    assert len(transport.calls) == 1 and used(database) == 1
    assert count(database, instruments) == 0 and count(database, research_runs) == 0
    assert count(database, raw_snapshots) == 0


def test_bad_financial_context_retains_raw_bytes_without_queued_run(database: Engine) -> None:
    values = payloads()
    values["net_income"]["cik"] = 456
    transport = SyntheticTransport(values)
    target = request()
    with pytest.raises(SecInputError):
        SecImporter(database, configured_policy(), transport).import_run(target)
    assert count(database, raw_snapshots) == 3 and count(database, research_runs) == 0
    assert count(database, report_revisions) == 0 and used(database) == 3
    with database.connect() as connection:
        snapshot_ids = connection.execute(select(raw_snapshots.c.snapshot_id)).scalars().all()
    actual = {SnapshotStore(database).content(snapshot_id)[1] for snapshot_id in snapshot_ids}
    assert actual == {transport.content(role) for role in SEC_ROLES_V1}


def test_403_consumes_one_attempt_without_fallback_or_fake_output(database: Engine) -> None:
    attempts: list[object] = []

    def blocked(value: object) -> SecResponse:
        attempts.append(value)
        raise SecTransportError("SEC_HTTP_403")

    with pytest.raises(SecTransportError, match="^SEC_HTTP_403$"):
        SecImporter(database, configured_policy(), blocked).import_run(request())
    assert len(attempts) == 1 and used(database) == 1
    assert count(database, raw_snapshots) == 0
    assert count(database, research_runs) == 0 and count(database, report_revisions) == 0


def test_partial_download_failure_retries_only_missing_resource_without_resetting_first_seen(
    database: Engine,
) -> None:
    generated = SyntheticTransport()
    attempts: list[str] = []
    failed = False

    def once_blocked(value: object) -> SecResponse:
        nonlocal failed
        assert isinstance(value, SecFetchRequest)
        attempts.append(value.resource)
        if value.resource == "net_income" and not failed:
            failed = True
            raise SecTransportError("SEC_HTTP_403")
        return generated(value)

    importer = SecImporter(database, configured_policy(), once_blocked)
    target = request()
    with pytest.raises(SecTransportError, match="^SEC_HTTP_403$"):
        importer.import_run(target)
    assert count(database, raw_snapshots) == 2 and count(database, research_runs) == 0
    with database.connect() as connection:
        checkpoint_ids = connection.execute(select(raw_snapshots.c.snapshot_id)).scalars().all()
    checkpoint = {key: SnapshotStore(database).content(key) for key in checkpoint_ids}
    completed = importer.import_run(target)
    assert completed.status == "queued" and used(database) == 4
    assert attempts == ["submissions", "revenue", "net_income", "net_income"]
    assert {key: SnapshotStore(database).content(key) for key in checkpoint_ids} == checkpoint


def test_public_raw_uploads_cannot_poison_sec_cache_or_create_verified_sec_run(
    database: Engine,
) -> None:
    from alphasense.instrument_contracts import InstrumentCreate

    target = request()
    transport = SyntheticTransport()
    first_seen = datetime(2024, 2, 3, 12, tzinfo=UTC)
    InstrumentStore(database).create(
        InstrumentCreate(
            schema_version="1.0",
            instrument_id=target.instrument_id,
            symbol=target.symbol,
            exchange_mic=target.exchange_mic,
            currency="USD",
            display_name="Synthetic SEC parser fixture",
            asset_type="equity",
            data_origin="live",
            as_of=first_seen,
            available_at=first_seen,
            source_id=SEC_SOURCE_IDS["submissions"],
            license=SEC_LICENSE,
            source_url=sec_url(SecFetchRequest(cik=CIK, resource="submissions")),
        )
    )
    poisoned_ids = []
    for role in ("submissions", "revenue", "net_income"):
        content = transport.content(role)
        poisoned = SnapshotCreate(
            schema_version="1.0",
            snapshot_id=uuid4(),
            instrument_id=target.instrument_id,
            data_origin="live",
            source_id=SEC_SOURCE_IDS[role],
            license=SEC_LICENSE,
            source_url=sec_url(SecFetchRequest.model_validate({"cik": CIK, "resource": role})),
            as_of=first_seen,
            available_at=first_seen,
            retrieved_at=first_seen,
            media_type="application/json",
            sha256=hashlib.sha256(content).hexdigest(),
            byte_length=len(content),
            content_base64=base64.b64encode(content).decode("ascii"),
        )
        SnapshotStore(database).create(poisoned)
        poisoned_ids.append(poisoned.snapshot_id)
    with pytest.raises(RunConflict):
        ResearchStore(database).create(
            RunCreate(
                schema_version="1.0",
                run_id=target.run_id,
                instrument_id=target.instrument_id,
                as_of=first_seen,
                snapshot_ids=poisoned_ids,
                pipeline_version=SEC_PIPELINE,
            )
        )
    assert count(database, research_runs) == 0
    before_fetch = datetime.now(UTC)
    state = SecImporter(database, configured_policy(), transport).import_run(target)
    assert len(transport.calls) == 3 and used(database) == 3
    assert set(state.snapshot_ids).isdisjoint(poisoned_ids)
    for snapshot_id in state.snapshot_ids:
        record = SnapshotStore(database).get(snapshot_id)
        assert record.retrieved_at >= before_fetch
    for snapshot_id in poisoned_ids:
        assert SnapshotStore(database).get(snapshot_id).retrieved_at == first_seen

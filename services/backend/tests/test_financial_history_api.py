"""Read-only history API binds an immutable report to its existing archive."""

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import alphasense.financial_history_api as module
from alphasense.api import app
from alphasense.db import ReportNotFound, get_store
from alphasense.financial_history import FinancialHistory, FinancialHistoryInvalid
from alphasense.report_contracts import ReportContent, seal_report
from alphasense.snapshots import SnapshotNotFound, get_snapshot_store


@pytest.fixture
def fixture_api(monkeypatch):
    value = json.loads((Path(__file__).parent / "fixtures/report.synthetic.json").read_text())
    value.pop("input_sha256")
    value.pop("checksum")
    snapshot_id = str(uuid4())
    value["input"]["observations"][0]["snapshot_id"] = snapshot_id
    value["sources"][0]["snapshot_id"] = snapshot_id
    report = seal_report(ReportContent.model_validate(value))
    reads = []

    def load(report_id, revision):
        reads.append(("report", str(report_id), revision))
        if report_id != report.report_id:
            raise ReportNotFound()
        return report

    def archived(snapshot_id):
        reads.append(("source", str(snapshot_id)))
        return "metadata", b"not part of the public response"

    def build(current, snapshots):
        assert current == report and snapshots == [("metadata", b"not part of the public response")]
        return FinancialHistory(
            report_id=report.report_id,
            revision=1,
            report_checksum=report.checksum,
            as_of=report.input.as_of,
            series=[],
            limitations=["Synthetic API transport test only."],
        )

    app.dependency_overrides[get_store] = lambda: SimpleNamespace(get_report=load)
    app.dependency_overrides[get_snapshot_store] = lambda: SimpleNamespace(content=archived)
    monkeypatch.setattr(module, "build_financial_history", build)
    try:
        with TestClient(app) as client:
            yield client, report, reads
    finally:
        app.dependency_overrides.clear()


def path(report):
    return f"/v1/panel/reports/{report.report_id}/1/financial-history"


def test_get_bound_identity_no_raw_source_or_mutation(fixture_api):
    client, report, reads = fixture_api
    response = client.get(path(report))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.json()["report_checksum"] == report.checksum
    assert len(reads) == 2 and "not part of the public response" not in response.text
    assert client.post(path(report), json={}).status_code == 405


def test_missing_report_and_invalid_revision(fixture_api):
    client, _, reads = fixture_api
    assert client.get(f"/v1/panel/reports/{uuid4()}/1/financial-history").status_code == 404
    reads.clear()
    assert client.get(f"/v1/panel/reports/{uuid4()}/0/financial-history").status_code == 422
    assert reads == []


def test_missing_archive_is_not_zero_history(fixture_api):
    client, report, _ = fixture_api

    def missing(_id):
        raise SnapshotNotFound()

    app.dependency_overrides[get_snapshot_store] = lambda: SimpleNamespace(content=missing)
    response = client.get(path(report))
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "HISTORY_ARCHIVE_UNAVAILABLE"


def test_unsupported_source_is_explicit_failure(fixture_api, monkeypatch):
    client, report, _ = fixture_api

    def denied(*args):
        raise FinancialHistoryInvalid("HISTORY_UNSUPPORTED")

    monkeypatch.setattr(module, "build_financial_history", denied)
    response = client.get(path(report))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "HISTORY_UNSUPPORTED"

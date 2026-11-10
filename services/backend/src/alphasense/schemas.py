"""Export or check schemas without accessing the network or resolving remote refs."""

import argparse
import json
from pathlib import Path

from pydantic import BaseModel, RootModel

from alphasense.contracts import HealthResult, ResearchInput, ValidationResult
from alphasense.document_archive_contracts import (
    DocumentArchiveCreate,
    DocumentArchivePage,
    DocumentArchiveRecord,
    DocumentReviewCommand,
    DocumentReviewEvent,
)
from alphasense.document_contracts import DocumentAgentResult, DocumentPacket, ExtractionDraft
from alphasense.instrument_contracts import (
    InstrumentCreate,
    InstrumentPage,
    InstrumentRecord,
    InstrumentWrite,
)
from alphasense.legacy import ReportInspection
from alphasense.provider_contracts import ProviderGrant, ProviderPolicy
from alphasense.report_contracts import ReportRevision
from alphasense.run_contracts import (
    RunCommand,
    RunCreate,
    RunEvent,
    RunEventPage,
    RunEventWrite,
    RunState,
    RunWrite,
)
from alphasense.sec_contracts import SecFetchRequest, SecImportRequest
from alphasense.snapshot_contracts import (
    SnapshotCreate,
    SnapshotMetadata,
    SnapshotPage,
    SnapshotRecord,
    SnapshotWrite,
)
from alphasense.storage_contracts import RevisionInfo, RevisionPage, StoredRevisionInfo
from alphasense.worker_contracts import WorkerJobRecord

ROOT = Path(__file__).resolve().parents[4]
MODELS: dict[str, type[BaseModel]] = {
    "document-archive-create": DocumentArchiveCreate,
    "document-archive-page": DocumentArchivePage,
    "document-archive-record": DocumentArchiveRecord,
    "document-review-command": DocumentReviewCommand,
    "document-review-event": DocumentReviewEvent,
    "document-packet": DocumentPacket,
    "document-extraction-draft": ExtractionDraft,
    "document-agent-result": DocumentAgentResult,
    "sec-fetch-request": SecFetchRequest,
    "sec-import-request": SecImportRequest,
    "provider-grant": ProviderGrant,
    "provider-policy": ProviderPolicy,
    "worker-job": WorkerJobRecord,
    "research-input": ResearchInput,
    "validation-result": ValidationResult,
    "health": HealthResult,
    "report": ReportRevision,
    "report-inspection": RootModel[ReportInspection],
    "revision-info": RevisionInfo,
    "stored-revision-info": StoredRevisionInfo,
    "revision-page": RevisionPage,
    "instrument-create": InstrumentCreate,
    "instrument-record": InstrumentRecord,
    "instrument-write": InstrumentWrite,
    "instrument-page": InstrumentPage,
    "snapshot-metadata": SnapshotMetadata,
    "snapshot-create": SnapshotCreate,
    "snapshot-record": SnapshotRecord,
    "snapshot-write": SnapshotWrite,
    "snapshot-page": SnapshotPage,
    "run-create": RunCreate,
    "run-command": RootModel[RunCommand],
    "run-state": RunState,
    "run-write": RunWrite,
    "run-event": RunEvent,
    "run-event-write": RunEventWrite,
    "run-event-page": RunEventPage,
}


def export(check: bool = False) -> None:
    destination = ROOT / "contracts" / "v1"
    for name, model in MODELS.items():
        schema = model.model_json_schema(mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"urn:alphasense:{name}:1.0"
        serialized = json.dumps(schema, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        path = destination / f"{name}.schema.json"
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != serialized:
                raise SystemExit(f"Schema drift: {path.relative_to(ROOT)}")
        else:
            destination.mkdir(parents=True, exist_ok=True)
            path.write_text(serialized, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    export(check=parser.parse_args().check)

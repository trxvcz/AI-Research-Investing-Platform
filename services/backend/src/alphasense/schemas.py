"""Export or check schemas without accessing the network or resolving remote refs."""

import argparse
import json
from pathlib import Path

from pydantic import BaseModel, RootModel

from alphasense.ai_analysis_contracts import AiAnalysisCreate, AiAnalysisRecord, AiBudget
from alphasense.ai_history_contracts import AiHistoryContext, AiHistoryNarrative
from alphasense.benchmark_corpus import CorpusManifest, CorpusProvenance
from alphasense.contracts import HealthResult, ResearchInput, ValidationResult
from alphasense.document_archive_contracts import (
    DocumentArchiveCreate,
    DocumentArchivePage,
    DocumentArchiveRecord,
    DocumentReviewCommand,
    DocumentReviewEvent,
)
from alphasense.document_benchmark_contracts import (
    BenchmarkResponses,
    BenchmarkResult,
    BenchmarkSuite,
)
from alphasense.document_contracts import DocumentAgentResult, DocumentPacket, ExtractionDraft
from alphasense.document_preview import DocumentPreviewCreate, DocumentPreviewResult
from alphasense.document_task_contracts import (
    DocumentTaskAudit,
    DocumentTaskCreate,
    DocumentTaskDetail,
    DocumentTaskPage,
    DocumentTaskRecord,
)
from alphasense.financial_history import FinancialHistory
from alphasense.financial_ratios import FinancialRatios
from alphasense.instrument_contracts import (
    InstrumentCreate,
    InstrumentPage,
    InstrumentRecord,
    InstrumentWrite,
)
from alphasense.legacy import ReportInspection
from alphasense.provider_contracts import ProviderGrant, ProviderPolicy
from alphasense.report_contracts import ReportRevision
from alphasense.research_export import ResearchExport
from alphasense.run_contracts import (
    RunCommand,
    RunCreate,
    RunEvent,
    RunEventPage,
    RunEventWrite,
    RunState,
    RunWrite,
)
from alphasense.schedule_contracts import (
    ScheduleCommand,
    ScheduleCreate,
    ScheduleOccurrencePage,
    SchedulePage,
    ScheduleRecord,
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
from alphasense.task_contracts import ImportTaskEventPage
from alphasense.worker_contracts import WorkerJobRecord
from alphasense.worker_session_contracts import WorkerSessionPage, WorkerSessionRecord

ROOT = Path(__file__).resolve().parents[4]
MODELS: dict[str, type[BaseModel]] = {
    "ai-history-context": AiHistoryContext,
    "ai-history-narrative": AiHistoryNarrative,
    "financial-history": FinancialHistory,
    "financial-ratios": FinancialRatios,
    "research-export": ResearchExport,
    "ai-analysis-create": AiAnalysisCreate,
    "ai-analysis-record": AiAnalysisRecord,
    "ai-budget": AiBudget,
    "document-preview-create": DocumentPreviewCreate,
    "document-preview-result": DocumentPreviewResult,
    "document-corpus-manifest": CorpusManifest,
    "document-corpus-provenance": CorpusProvenance,
    "document-benchmark-suite": BenchmarkSuite,
    "document-benchmark-responses": BenchmarkResponses,
    "document-benchmark-result": BenchmarkResult,
    "import-task-event-page": ImportTaskEventPage,
    "schedule-create": ScheduleCreate,
    "schedule-command": ScheduleCommand,
    "schedule-record": ScheduleRecord,
    "schedule-page": SchedulePage,
    "schedule-occurrence-page": ScheduleOccurrencePage,
    "worker-session-record": WorkerSessionRecord,
    "worker-session-page": WorkerSessionPage,
    "document-task-create": DocumentTaskCreate,
    "document-task-record": DocumentTaskRecord,
    "document-task-page": DocumentTaskPage,
    "document-task-detail": DocumentTaskDetail,
    "document-task-audit": DocumentTaskAudit,
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

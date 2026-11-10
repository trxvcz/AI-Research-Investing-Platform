"""Versioned deterministic report envelope; validates declarations, not their truth."""

import hashlib
import json
import re
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AnyHttpUrl, BeforeValidator, Field, StringConstraints, model_validator

from alphasense.contracts import (
    AvailableObservation,
    Contract,
    Identifier,
    Reason,
    ResearchInput,
    Timestamp,
    summarize,
)

Sha256 = Annotated[
    str,
    StringConstraints(strict=True, min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$"),
]
GitSha = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$"),
    Field(json_schema_extra={"not": {"pattern": r"\s$"}}),
]
RevisionNumber = Annotated[int, Field(strict=True, ge=1)]
ObservationIndex = Annotated[int, Field(strict=True, ge=0, le=999)]
ReportStatus = Literal["complete", "partial", "blocked", "failed"]
DISCLAIMER = "Research only. No order execution or personalized investment advice."
UUID_PATTERN = r"[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}"
HTTP_PATTERN = r"^[hH][tT][tT][pP][sS]?://"


def uuid_input(value: object) -> UUID | str:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str) or not re.fullmatch(UUID_PATTERN, value):
        raise ValueError("hyphenated UUID required")
    return value


def http_url_input(value: object) -> object:
    if (
        not isinstance(value, (str, AnyHttpUrl))
        or not re.match(HTTP_PATTERN, str(value))
        or re.search(r"\s", str(value))
    ):
        raise ValueError("HTTP(S) URL required")
    return value


ReportUUID = Annotated[
    UUID,
    BeforeValidator(uuid_input),
    Field(json_schema_extra={"pattern": f"^{UUID_PATTERN}$", "not": {"pattern": r"\s$"}}),
]
SourceURL = Annotated[
    AnyHttpUrl,
    BeforeValidator(http_url_input),
    Field(json_schema_extra={"pattern": HTTP_PATTERN}),
]


def canonical_sha256(value: object) -> str:
    """Hash normalized JSON values, not original files or an RFC8785 representation."""
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class SourceProvenance(Contract):
    source_id: Identifier
    snapshot_id: Identifier
    sha256: Sha256
    url: SourceURL | None
    retrieved_at: Timestamp
    license: Reason


class Finding(Contract):
    kind: Literal["fact", "calculation", "assumption", "interpretation"]
    text: Reason
    observation_indexes: Annotated[list[ObservationIndex], Field(max_length=1000)]
    method: Identifier | None

    @model_validator(mode="after")
    def check_evidence(self) -> Self:
        if len(set(self.observation_indexes)) != len(self.observation_indexes):
            raise ValueError("duplicate observation index")
        if self.kind != "assumption" and not self.observation_indexes:
            raise ValueError("evidence required")
        if (self.kind == "calculation") != (self.method is not None):
            raise ValueError("method required only for calculations")
        return self


class ReportSection(Contract):
    status: Literal["complete", "partial", "blocked", "failed", "not_applicable"]
    findings: Annotated[list[Finding], Field(max_length=100)]
    reason: Reason | None

    @model_validator(mode="after")
    def check_completeness(self) -> Self:
        productive = self.status in {"complete", "partial"}
        if productive != bool(self.findings):
            raise ValueError("section findings conflict with status")
        if (self.status == "complete") != (self.reason is None):
            raise ValueError("reason required unless section is complete")
        return self


class ReportContent(Contract):
    schema_version: Literal["1.0"]
    report_id: ReportUUID
    revision_id: ReportUUID
    parent_revision_id: ReportUUID | None
    revision: RevisionNumber
    generated_at_utc: Timestamp
    input: ResearchInput
    status: ReportStatus
    methodology_version: Identifier
    pipeline_git_sha: GitSha
    sources: Annotated[list[SourceProvenance], Field(max_length=1000)]
    fundamental_section: ReportSection
    technical_section: ReportSection
    synthesis_section: ReportSection
    scenario_section: ReportSection
    uncertainties: Annotated[list[Reason], Field(max_length=32)]
    limitations: Annotated[list[Reason], Field(min_length=1, max_length=32)]
    disclaimer: Literal["Research only. No order execution or personalized investment advice."]
    model_provenance: None
    prompt_template_version: None
    chart_artifact_ids: Annotated[list[Identifier], Field(max_length=0)]

    @model_validator(mode="after")
    def check_revision_and_time(self) -> Self:
        if (self.revision == 1) != (self.parent_revision_id is None):
            raise ValueError("revision parent required after first revision")
        if self.parent_revision_id == self.revision_id:
            raise ValueError("revision cannot be its own parent")
        if self.generated_at_utc < self.input.as_of:
            raise ValueError("report generated before data cutoff")
        return self

    @model_validator(mode="after")
    def check_provenance(self) -> Self:
        sources = {(item.source_id, item.snapshot_id): item for item in self.sources}
        if len(sources) != len(self.sources):
            raise ValueError("duplicate source snapshot")
        observations = [
            item for item in self.input.observations if isinstance(item, AvailableObservation)
        ]
        expected = {(item.source_id, item.snapshot_id) for item in observations}
        if set(sources) != expected:
            raise ValueError("sources must exactly cover available observations")
        for item in observations:
            source = sources[(item.source_id, item.snapshot_id)]
            if not item.available_at <= source.retrieved_at <= self.generated_at_utc:
                raise ValueError("source retrieval time conflicts with availability")
            if self.input.data_origin == "live" and source.url is None:
                raise ValueError("live source URL required")
        return self

    @model_validator(mode="after")
    def check_findings_and_status(self) -> Self:
        sections = (
            self.fundamental_section,
            self.technical_section,
            self.synthesis_section,
            self.scenario_section,
        )
        for section in sections:
            for finding in section.findings:
                for index in finding.observation_indexes:
                    if index >= len(self.input.observations):
                        raise ValueError("unknown observation index")
                    if self.input.observations[index].status != "available":
                        raise ValueError("finding references unavailable observation")
        completeness = summarize(self.input).status
        expected: ReportStatus
        if any(section.status == "failed" for section in sections):
            expected = "failed"
        elif completeness == "blocked" or not any(
            section.status in {"complete", "partial"} for section in sections
        ):
            expected = "blocked"
        elif completeness == "complete" and all(
            section.status in {"complete", "not_applicable"} for section in sections
        ):
            expected = "complete"
        else:
            expected = "partial"
        if self.status != expected:
            raise ValueError("report status conflicts with sections or observations")
        return self


class ReportRevision(ReportContent):
    input_sha256: Sha256
    checksum: Sha256

    @model_validator(mode="after")
    def check_checksums(self) -> Self:
        if self.input_sha256 != canonical_sha256(self.input.model_dump(mode="json")):
            raise ValueError("input checksum mismatch")
        if self.checksum != canonical_sha256(self.model_dump(mode="json", exclude={"checksum"})):
            raise ValueError("report checksum mismatch")
        return self


def seal_report(content: ReportContent) -> ReportRevision:
    """Validate again before sealing: mutable model instances are not trusted."""
    checked = ReportContent.model_validate(content.model_dump(mode="python"))
    payload = checked.model_dump(mode="json")
    payload["input_sha256"] = canonical_sha256(checked.input.model_dump(mode="json"))
    payload["checksum"] = canonical_sha256(payload)
    return ReportRevision.model_validate(payload)

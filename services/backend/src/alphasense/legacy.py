"""Inspect supplied reports without upgrading, persisting or fetching their data."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema import ValidationError as SchemaValidationError
from pydantic import Field, StringConstraints, ValidationError
from referencing import Registry

from alphasense.contracts import Contract
from alphasense.report_contracts import ReportRevision, ReportUUID

LegacyStatus = Literal["demo", "partial", "blocked", "complete", "failed"]
ReportStatus = Literal["complete", "partial", "blocked", "failed"]
Checksum = Annotated[
    str,
    StringConstraints(strict=True, min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$"),
]


class InvalidReportError(ValueError):
    """The supplied report is invalid; this exception contains no payload data."""


class LegacyInspection(Contract):
    format: Literal["legacy-m0"] = "legacy-m0"
    # Preserve the original legacy id contract instead of inventing a UUID.
    report_id: Annotated[str, StringConstraints(strict=True, min_length=1)]
    legacy_status: LegacyStatus
    migration_status: Literal["blocked_missing_provenance"] = "blocked_missing_provenance"
    missing_fields: tuple[
        Literal["observation_available_at"],
        Literal["observation_periods"],
        Literal["snapshot_provenance"],
    ] = ("observation_available_at", "observation_periods", "snapshot_provenance")


class V1Inspection(Contract):
    format: Literal["v1"] = "v1"
    schema_version: Literal["1.0"]
    report_id: ReportUUID
    revision_id: ReportUUID
    revision: Annotated[int, Field(strict=True, gt=0)]
    status: ReportStatus
    data_origin: Literal["synthetic", "live"]
    checksum: Checksum


ReportInspection = Annotated[LegacyInspection | V1Inspection, Field(discriminator="format")]


@lru_cache(maxsize=1)
def _legacy_validator() -> Draft202012Validator:
    schema_path = Path(__file__).resolve().parents[4] / "contracts" / "report.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
        # An explicit Registry has no retrieval callback: unknown resources fail
        # closed instead of jsonschema's default legacy remote-ref retrieval.
        registry=Registry(),
    )


def inspect_report(payload: dict[str, Any]) -> ReportInspection:
    """Validate an explicit version or recognize M0 without claiming provenance."""
    if not isinstance(payload, dict):
        raise InvalidReportError("Invalid report data")
    try:
        # JSON Schema's Python object validator otherwise permits NaN/Infinity in
        # legacy open metric objects, even though they are not JSON numbers.
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise InvalidReportError("Invalid report data") from error

    if "schema_version" in payload:
        try:
            report = ReportRevision.model_validate(payload)
        except ValidationError as error:
            raise InvalidReportError("Invalid report data") from error
        return V1Inspection(
            schema_version="1.0",
            report_id=report.report_id,
            revision_id=report.revision_id,
            revision=report.revision,
            status=report.status,
            data_origin=report.input.data_origin,
            checksum=report.checksum,
        )

    # Reading/checking the fixed schema is infrastructure work. Do not disguise
    # I/O or schema-definition errors as bad client data.
    validator = _legacy_validator()
    try:
        validator.validate(payload)
    except SchemaValidationError as error:
        raise InvalidReportError("Invalid report data") from error
    return LegacyInspection(report_id=payload["id"], legacy_status=payload["status"])

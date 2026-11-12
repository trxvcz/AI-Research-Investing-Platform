"""Prepare and verify private, source-bound benchmark samples without fetching URLs."""

import base64
import hashlib
import json
import os
import re
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, StringConstraints, model_validator

from alphasense.contracts import Contract, Identifier, Timestamp
from alphasense.document_benchmark import canonical_hash
from alphasense.document_benchmark_contracts import BenchmarkCase, BenchmarkSuite, GoldFact
from alphasense.document_contracts import NumberLocale, ReaderVersion, validate_reader_options
from alphasense.document_readers import read_text_document
from alphasense.instrument_contracts import InstrumentURL
from alphasense.report_contracts import Sha256

MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_SOURCE_BYTES = 64 * 1024 * 1024
MAX_EXCERPT_BYTES = 1024 * 1024
MAX_SUITE_BYTES = 8 * 1024 * 1024
MAX_JSON_BYTES = 16 * 1024 * 1024
Format = Literal["text", "html", "pdf", "xlsx"]
Text = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=512)]
Count = Annotated[int, Field(strict=True, ge=0)]
_SUFFIX = {"text": ".txt", "html": ".html", "pdf": ".pdf", "xlsx": ".xlsx"}
_ALLOWED_SUFFIXES = {
    "text": {".txt"},
    "html": {".html", ".htm"},
    "pdf": {".pdf"},
    "xlsx": {".xlsx"},
}


class CorpusInvalid(ValueError):
    """Stable refusal without source text, filesystem paths or parser diagnostics."""


class CorpusRange(Contract):
    start: Annotated[int, Field(strict=True, ge=0, le=MAX_SOURCE_BYTES)]
    end: Annotated[int, Field(strict=True, ge=1, le=MAX_SOURCE_BYTES)]

    @model_validator(mode="after")
    def nonempty(self) -> Self:
        if self.start >= self.end:
            raise ValueError("Invalid source range")
        return self


class CorpusCase(Contract):
    case_id: Identifier
    issuer_label: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)]
    format: Format
    reader_version: ReaderVersion | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    number_locale: NumberLocale | None = Field(default=None, exclude_if=lambda value: value is None)
    source_file: Text
    source_url: Annotated[
        InstrumentURL,
        Field(
            json_schema_extra={
                "pattern": r"^[hH][tT][tT][pP][sS]://",
                "not": {
                    "anyOf": [
                        {"pattern": r"[\x00-\x1f\x7f]"},
                        {"pattern": r"^[hH][tT][tT][pP][sS]://[^/?#]*@"},
                    ]
                },
            }
        ),
    ]
    source_sha256: Sha256
    first_seen_at: Timestamp
    as_of: Timestamp
    title: Text
    source_locator: Text
    annotation_status: Literal["draft", "independently_reviewed"] = "draft"
    reviewer_note: Annotated[str, StringConstraints(strict=True, max_length=2000)] = ""
    gold: Annotated[list[GoldFact], Field(max_length=64)]
    sampling: Literal["whole_document", "exact_byte_ranges"] = "whole_document"
    ranges: Annotated[list[CorpusRange], Field(max_length=32)] = Field(default_factory=list)

    @model_validator(mode="after")
    def safe_declarations(self) -> Self:
        validate_reader_options(self.format, self.reader_version, self.number_locale)
        _relative_parts(self.source_file)
        if PurePosixPath(self.source_file).suffix.lower() not in _ALLOWED_SUFFIXES[self.format]:
            raise ValueError("Source format mismatch")
        if (
            self.source_url.scheme != "https"
            or self.source_url.username is not None
            or self.source_url.password is not None
        ):
            raise ValueError("HTTPS source metadata required")
        if self.first_seen_at > self.as_of:
            raise ValueError("Source was unavailable at cutoff")
        for value in (
            self.case_id,
            self.issuer_label,
            self.title,
            self.source_locator,
            self.reviewer_note,
        ):
            if re.search(r"[\x00-\x1f\x7f]", value):
                raise ValueError("Control characters in metadata")
        if not all(value.strip() for value in (self.issuer_label, self.title, self.source_locator)):
            raise ValueError("Empty source metadata")
        if self.annotation_status == "independently_reviewed" and not self.reviewer_note.strip():
            raise ValueError("Review declaration required")
        if self.sampling == "whole_document":
            if self.ranges:
                raise ValueError("Whole document cannot specify ranges")
        elif self.format not in {"text", "html"} or not self.ranges:
            raise ValueError("UTF-8 text ranges required")
        previous_end = 0
        for item in self.ranges:
            if item.start < previous_end:
                raise ValueError("Unordered or overlapping source ranges")
            previous_end = item.end
        return self


class CorpusManifest(Contract):
    schema_version: Literal["1.0"]
    suite_id: Identifier
    cases: Annotated[list[CorpusCase], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def unique_cases(self) -> Self:
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("Duplicate corpus case")
        return self


class CorpusEntry(Contract):
    case_id: Identifier
    source_file: Text
    source_sha256: Sha256
    source_byte_length: Annotated[int, Field(strict=True, ge=1, le=MAX_SOURCE_BYTES)]
    excerpt_file: Text
    excerpt_sha256: Sha256
    excerpt_byte_length: Annotated[int, Field(strict=True, ge=1, le=MAX_EXCERPT_BYTES)]


class CorpusProvenance(Contract):
    schema_version: Literal["1.0"] = "1.0"
    manifest: CorpusManifest
    manifest_sha256: Sha256
    suite_sha256: Sha256
    entries: Annotated[list[CorpusEntry], Field(min_length=1, max_length=32)]
    qualification_status: Literal["not_qualified_offline"] = "not_qualified_offline"


def _relative_parts(value: str) -> tuple[str, ...]:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or ":" in value
        or any(part in {".", ".."} for part in path.parts)
        or path.as_posix() != value
        or re.search(r"[\x00-\x1f\x7f]", value)
    ):
        raise ValueError("Invalid relative source path")
    return path.parts


def _bounded_file(base: Path, relative: str, limit: int) -> bytes:
    parts = _relative_parts(relative)
    target = base.joinpath(*parts).resolve(strict=True)
    if not target.is_relative_to(base) or not target.is_file():
        raise ValueError("Source path escapes corpus")
    with target.open("rb") as source:
        raw = source.read(limit + 1)
    if not 1 <= len(raw) <= limit:
        raise ValueError("Source byte limit")
    return raw


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _constant(_value: str) -> object:
    raise ValueError("Non-JSON constant")


def _json(raw: bytes) -> object:
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_constant)


def _sample(case: CorpusCase, raw: bytes) -> bytes:
    if case.sampling == "whole_document":
        excerpt = raw
    else:
        raw.decode("utf-8")
        chunks = []
        for item in case.ranges:
            if item.end > len(raw):
                raise ValueError("Source range exceeds original")
            chunk = raw[item.start : item.end]
            chunk.decode("utf-8")
            chunks.append(chunk)
        excerpt = b"\n".join(chunks)
    if not 1 <= len(excerpt) <= MAX_EXCERPT_BYTES:
        raise ValueError("Excerpt byte limit")
    return excerpt


def _build(
    manifest: CorpusManifest, source: Callable[[int, CorpusCase], bytes]
) -> tuple[BenchmarkSuite, CorpusProvenance, list[bytes], list[bytes]]:
    manifest = CorpusManifest.model_validate(manifest.model_dump(mode="python", warnings=False))
    manifest_hash = canonical_hash(manifest)
    originals = []
    total_source = 0
    for index, case in enumerate(manifest.cases, 1):
        raw = source(index, case)
        total_source += len(raw)
        if (
            not 1 <= len(raw) <= MAX_SOURCE_BYTES
            or total_source > MAX_TOTAL_SOURCE_BYTES
            or hashlib.sha256(raw).hexdigest() != case.source_sha256
        ):
            raise ValueError("Source identity or byte limit")
        originals.append(raw)
    samples: list[bytes] = []
    cases: list[BenchmarkCase] = []
    entries: list[CorpusEntry] = []
    total_samples = 0
    for index, (case, raw) in enumerate(zip(manifest.cases, originals, strict=True), 1):
        excerpt = _sample(case, raw)
        total_samples += len(excerpt)
        if total_samples > MAX_SUITE_BYTES:
            raise ValueError("Benchmark suite byte limit")
        read_text_document(
            excerpt,
            document_id=uuid5(NAMESPACE_URL, manifest_hash + ":" + case.case_id),
            classification="private",
            format=case.format,
            reader_version=case.reader_version,
            number_locale=case.number_locale,
        )
        digest = hashlib.sha256(excerpt).hexdigest()
        suffix = _SUFFIX[case.format]
        samples.append(excerpt)
        cases.append(
            BenchmarkCase(
                case_id=case.case_id,
                issuer_label=case.issuer_label,
                format=case.format,
                reader_version=case.reader_version,
                number_locale=case.number_locale,
                classification="private",
                data_origin="user_supplied",
                content_base64=base64.b64encode(excerpt).decode("ascii"),
                document_sha256=digest,
                source_available_at=case.first_seen_at,
                as_of=case.as_of,
                expected_facts=case.gold,
            )
        )
        entries.append(
            CorpusEntry(
                case_id=case.case_id,
                source_file=f"sources/{index:04d}{suffix}",
                source_sha256=case.source_sha256,
                source_byte_length=len(raw),
                excerpt_file=f"excerpts/{index:04d}{suffix}",
                excerpt_sha256=digest,
                excerpt_byte_length=len(excerpt),
            )
        )
    suite = BenchmarkSuite(schema_version="1.0", suite_id=manifest.suite_id, cases=cases)
    provenance = CorpusProvenance(
        manifest=manifest,
        manifest_sha256=manifest_hash,
        suite_sha256=canonical_hash(suite),
        entries=entries,
    )
    return suite, provenance, originals, samples


def _write(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as destination:
        destination.write(raw)
    if os.name != "nt":
        path.chmod(0o600)


def _serialize(model: Contract) -> bytes:
    return (json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )


def _summary(provenance: CorpusProvenance) -> dict[str, object]:
    reviewed = sum(
        case.annotation_status == "independently_reviewed" for case in provenance.manifest.cases
    )
    return {
        "case_count": len(provenance.entries),
        "suite_sha256": provenance.suite_sha256,
        "draft_annotations": len(provenance.entries) - reviewed,
        "independently_reviewed_annotations": reviewed,
        "qualification_status": "not_qualified_offline",
        "model_called": False,
    }


def prepare_corpus(
    manifest: CorpusManifest, base_directory: Path, output_directory: Path
) -> dict[str, object]:
    """Validate all inputs before creating a new private corpus directory."""
    try:
        if not isinstance(manifest, CorpusManifest):
            raise ValueError("Corpus manifest required")
        base = Path(base_directory).resolve(strict=True)
        suite, provenance, originals, samples = _build(
            manifest, lambda _index, case: _bounded_file(base, case.source_file, MAX_SOURCE_BYTES)
        )
        output = Path(output_directory)
        output.mkdir(mode=0o700, parents=False, exist_ok=False)
        if os.name != "nt":
            output.chmod(0o700)
        for name in ("sources", "excerpts"):
            directory = output / name
            directory.mkdir(mode=0o700)
            if os.name != "nt":
                directory.chmod(0o700)
        for entry, original, sample in zip(provenance.entries, originals, samples, strict=True):
            _write(output / entry.source_file, original)
            _write(output / entry.excerpt_file, sample)
        _write(output / "suite.json", _serialize(suite))
        _write(output / "provenance.json", _serialize(provenance))
        return _summary(provenance)
    except (OSError, ValueError, TypeError, RecursionError, AttributeError, OverflowError):
        raise CorpusInvalid("DOCUMENT_CORPUS_INVALID") from None


def verify_corpus(output_directory: Path) -> dict[str, object]:
    """Reconstruct every excerpt and the suite from the saved, bounded originals."""
    try:
        base = Path(output_directory).resolve(strict=True)
        provenance = CorpusProvenance.model_validate(
            _json(_bounded_file(base, "provenance.json", MAX_JSON_BYTES))
        )
        suite = BenchmarkSuite.model_validate(
            _json(_bounded_file(base, "suite.json", MAX_JSON_BYTES))
        )
        if len(provenance.entries) != len(provenance.manifest.cases):
            raise ValueError("Corpus entry coverage")
        for index, (case, entry) in enumerate(
            zip(provenance.manifest.cases, provenance.entries, strict=True), 1
        ):
            suffix = _SUFFIX[case.format]
            if (
                entry.case_id != case.case_id
                or entry.source_file != f"sources/{index:04d}{suffix}"
                or entry.excerpt_file != f"excerpts/{index:04d}{suffix}"
            ):
                raise ValueError("Corpus entry identity")
        rebuilt, expected, _originals, samples = _build(
            provenance.manifest,
            lambda index, _case: _bounded_file(
                base, provenance.entries[index - 1].source_file, MAX_SOURCE_BYTES
            ),
        )
        if provenance != expected or canonical_hash(suite) != canonical_hash(rebuilt):
            raise ValueError("Corpus manifest, suite or provenance changed")
        for entry, sample in zip(provenance.entries, samples, strict=True):
            if _bounded_file(base, entry.excerpt_file, MAX_EXCERPT_BYTES) != sample:
                raise ValueError("Stored excerpt changed")
        return _summary(provenance)
    except (OSError, ValueError, TypeError, RecursionError, AttributeError, OverflowError):
        raise CorpusInvalid("DOCUMENT_CORPUS_INVALID") from None

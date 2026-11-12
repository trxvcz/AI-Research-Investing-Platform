"""Source-bound samples are local, private and reconstructible, never model evidence."""

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from alphasense import benchmark_corpus
from alphasense.benchmark_corpus import (
    CorpusCase,
    CorpusInvalid,
    CorpusManifest,
    prepare_corpus,
    verify_corpus,
)
from alphasense.document_benchmark_contracts import BenchmarkSuite

RAW = b"Header: synthetic source\nConsolidated revenue 2025: 12.5 million PLN.\nFooter"


def manifest(base: Path, **updates) -> CorpusManifest:
    (base / "source.txt").write_bytes(RAW)
    case = {
        "case_id": "issuer-a",
        "issuer_label": "Synthetic source for corpus tests",
        "format": "text",
        "source_file": "source.txt",
        "source_url": "https://issuer.example/report.txt",
        "source_sha256": hashlib.sha256(RAW).hexdigest(),
        "first_seen_at": "2026-01-01T00:00:00Z",
        "as_of": "2026-01-02T00:00:00Z",
        "title": "Annual reference",
        "source_locator": "Revenue statement",
        "gold": [
            {
                "metric": "revenue",
                "value": "12500000",
                "currency": "PLN",
                "period_start": "2025-01-01",
                "period_end": "2025-12-31",
                "scope": "consolidated",
            }
        ],
    }
    case.update(updates)
    return CorpusManifest.model_validate(
        {"schema_version": "1.0", "suite_id": "test-corpus", "cases": [case]}
    )


def prepared(tmp_path, **updates):
    value = manifest(tmp_path, **updates)
    output = tmp_path / "prepared"
    summary = prepare_corpus(value, tmp_path, output)
    return value, output, summary


def test_whole_document_private_roundtrip_and_no_model_claim(tmp_path):
    original, output, summary = prepared(tmp_path)
    assert verify_corpus(output) == summary
    assert summary["case_count"] == summary["draft_annotations"] == 1
    assert summary["independently_reviewed_annotations"] == 0
    assert summary["qualification_status"] == "not_qualified_offline"
    assert summary["model_called"] is False
    assert (output / "sources/0001.txt").read_bytes() == RAW
    assert (output / "excerpts/0001.txt").read_bytes() == RAW
    suite = BenchmarkSuite.model_validate_json((output / "suite.json").read_text("utf-8"))
    assert suite.cases[0].classification == "private"
    assert suite.cases[0].data_origin == "user_supplied"
    assert suite.cases[0].source_available_at == original.cases[0].first_seen_at
    assert suite.cases[0].expected_facts == original.cases[0].gold
    if os.name != "nt":
        assert output.stat().st_mode & 0o777 == 0o700
        assert (output / "sources").stat().st_mode & 0o777 == 0o700
        for file in output.rglob("*"):
            if file.is_file():
                assert file.stat().st_mode & 0o777 == 0o600


def test_byte_ranges_are_exact_ordered_and_bound_to_original(tmp_path):
    start = RAW.index(b"Consolidated")
    end = RAW.index(b"\nFooter")
    _, output, _ = prepared(
        tmp_path,
        sampling="exact_byte_ranges",
        ranges=[{"start": 0, "end": 6}, {"start": start, "end": end}],
    )
    assert (output / "excerpts/0001.txt").read_bytes() == RAW[:6] + b"\n" + RAW[start:end]
    assert (output / "sources/0001.txt").read_bytes() == RAW
    assert verify_corpus(output)["case_count"] == 1


def test_draft_is_never_promoted_and_review_requires_explicit_note(tmp_path):
    with pytest.raises(ValidationError):
        manifest(tmp_path, annotation_status="independently_reviewed", reviewer_note=" ")
    _, output, summary = prepared(
        tmp_path,
        annotation_status="independently_reviewed",
        reviewer_note="Independent check declared",
    )
    assert summary["independently_reviewed_annotations"] == 1
    assert verify_corpus(output) == summary


@pytest.mark.parametrize(
    "path",
    [
        "../outside.txt",
        "/absolute.txt",
        "C:/private.txt",
        "a\\b.txt",
        "./source.txt",
        "a//source.txt",
        "source.env",
    ],
)
def test_noncanonical_or_unsafe_source_paths_rejected(tmp_path, path):
    with pytest.raises(ValidationError):
        manifest(tmp_path, source_file=path)


def test_symlink_outside_source_directory_is_rejected(tmp_path):
    base = tmp_path / "inputs"
    base.mkdir()
    original = manifest(base)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(RAW)
    (base / "source.txt").unlink()
    try:
        (base / "source.txt").symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this host")
    with pytest.raises(CorpusInvalid, match="^DOCUMENT_CORPUS_INVALID$"):
        prepare_corpus(original, base, tmp_path / "prepared")
    assert not (tmp_path / "prepared").exists()


@pytest.mark.parametrize(
    "updates",
    [
        {"source_sha256": "a" * 64},
        {"sampling": "exact_byte_ranges", "ranges": [{"start": 0, "end": len(RAW) + 1}]},
    ],
)
def test_source_mismatch_precedes_output_creation(tmp_path, updates):
    original = manifest(tmp_path, **updates)
    with pytest.raises(CorpusInvalid, match="^DOCUMENT_CORPUS_INVALID$"):
        prepare_corpus(original, tmp_path, tmp_path / "prepared")
    assert not (tmp_path / "prepared").exists()


@pytest.mark.parametrize(
    "updates",
    [
        {"source_url": "http://issuer.example/report.txt"},
        {"source_url": "https://user:password@issuer.example/report.txt"},
        {"first_seen_at": "2026-01-03T00:00:00Z"},
        {"sampling": "whole_document", "ranges": [{"start": 0, "end": 1}]},
        {"sampling": "exact_byte_ranges", "ranges": []},
        {
            "sampling": "exact_byte_ranges",
            "ranges": [{"start": 5, "end": 10}, {"start": 9, "end": 11}],
        },
        {"title": "private\ncontrol"},
    ],
)
def test_invalid_metadata_or_sampling_rejected(tmp_path, updates):
    with pytest.raises(ValidationError):
        manifest(tmp_path, **updates)


@pytest.mark.parametrize(
    "url",
    [
        "http://issuer.example/report.txt",
        "https://user:password@issuer.example/report.txt",
        "https://user@issuer.example/report.txt",
        "https://issuer.example/private\nreport.txt",
    ],
)
def test_source_url_schema_and_runtime_reject_the_same_unsafe_metadata(tmp_path, url):
    payload = manifest(tmp_path).cases[0].model_dump(mode="json")
    payload["source_url"] = url
    schema = CorpusCase.model_json_schema()
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    assert list(validator.iter_errors(payload))
    with pytest.raises(ValidationError):
        CorpusCase.model_validate(payload)


def test_source_url_schema_accepts_https_and_does_not_ban_at_sign_in_path(tmp_path):
    payload = manifest(tmp_path).cases[0].model_dump(mode="json")
    payload["source_url"] = "https://issuer.example/report@2025.txt"
    validator = Draft202012Validator(CorpusCase.model_json_schema(), format_checker=FormatChecker())
    validator.validate(payload)
    assert CorpusCase.model_validate(payload).source_url.scheme == "https"


def test_duplicate_case_ids_are_rejected(tmp_path):
    payload = manifest(tmp_path).model_dump(mode="json")
    payload["cases"].append(deepcopy(payload["cases"][0]))
    with pytest.raises(ValidationError):
        CorpusManifest.model_validate(payload)


def test_mutated_nested_contract_is_revalidated(tmp_path):
    original = manifest(tmp_path)
    original.cases[0].source_file = "../private.txt"
    with pytest.raises(CorpusInvalid, match="^DOCUMENT_CORPUS_INVALID$"):
        prepare_corpus(original, tmp_path, tmp_path / "prepared")


def test_empty_source_is_refused_without_partial_artifact(tmp_path):
    original = manifest(tmp_path)
    (tmp_path / "source.txt").write_bytes(b"")
    original.cases[0].source_sha256 = hashlib.sha256(b"").hexdigest()
    with pytest.raises(CorpusInvalid):
        prepare_corpus(original, tmp_path, tmp_path / "prepared")
    assert not (tmp_path / "prepared").exists()


def test_whole_document_larger_than_benchmark_limit_is_not_silently_truncated(tmp_path):
    original = manifest(tmp_path)
    raw = b"a" * (1024 * 1024 + 1)
    (tmp_path / "source.txt").write_bytes(raw)
    original.cases[0].source_sha256 = hashlib.sha256(raw).hexdigest()
    with pytest.raises(CorpusInvalid):
        prepare_corpus(original, tmp_path, tmp_path / "prepared")


def test_total_sources_limit_is_checked_before_parsing(tmp_path, monkeypatch):
    original = manifest(tmp_path)
    monkeypatch.setattr(benchmark_corpus, "MAX_TOTAL_SOURCE_BYTES", len(RAW) - 1)

    def forbidden(*args, **kwargs):
        pytest.fail("Parser reached before source limit validation")

    monkeypatch.setattr(benchmark_corpus, "read_text_document", forbidden)
    with pytest.raises(CorpusInvalid):
        prepare_corpus(original, tmp_path, tmp_path / "prepared")


def test_single_source_read_is_bounded_before_hash_or_parsing(tmp_path, monkeypatch):
    original = manifest(tmp_path)
    monkeypatch.setattr(benchmark_corpus, "MAX_SOURCE_BYTES", len(RAW) - 1)
    with pytest.raises(CorpusInvalid):
        prepare_corpus(original, tmp_path, tmp_path / "prepared")
    assert not (tmp_path / "prepared").exists()


def test_case_identifiers_are_never_used_as_filesystem_paths(tmp_path):
    _, output, summary = prepared(tmp_path, case_id="../not-a-path")
    assert (output / "sources/0001.txt").read_bytes() == RAW
    assert verify_corpus(output) == summary


def test_excerpt_total_limit_is_checked_without_writing(tmp_path, monkeypatch):
    original = manifest(tmp_path)
    monkeypatch.setattr(benchmark_corpus, "MAX_SUITE_BYTES", len(RAW) - 1)
    with pytest.raises(CorpusInvalid):
        prepare_corpus(original, tmp_path, tmp_path / "prepared")
    assert not (tmp_path / "prepared").exists()


def test_unreadable_document_refuses_the_entire_corpus_before_writing(tmp_path):
    original = manifest(tmp_path)
    raw = b"\xff\xfe\x00unreadable"
    (tmp_path / "source.txt").write_bytes(raw)
    original.cases[0].source_sha256 = hashlib.sha256(raw).hexdigest()
    with pytest.raises(CorpusInvalid):
        prepare_corpus(original, tmp_path, tmp_path / "prepared")
    assert not (tmp_path / "prepared").exists()


def test_ranges_are_not_a_pdf_page_extraction_instruction(tmp_path):
    with pytest.raises(ValidationError):
        manifest(
            tmp_path,
            format="pdf",
            source_file="source.pdf",
            sampling="exact_byte_ranges",
            ranges=[{"start": 0, "end": 1}],
        )


def test_range_cannot_split_utf8_character(tmp_path):
    raw = "Revenue ą 12".encode()
    original = manifest(tmp_path, sampling="exact_byte_ranges", ranges=[{"start": 0, "end": 9}])
    (tmp_path / "source.txt").write_bytes(raw)
    original.cases[0].source_sha256 = hashlib.sha256(raw).hexdigest()
    with pytest.raises(CorpusInvalid):
        prepare_corpus(original, tmp_path, tmp_path / "prepared")


def test_existing_directory_and_its_files_are_untouched(tmp_path):
    original = manifest(tmp_path)
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "user-work.txt"
    marker.write_bytes(b"preserve")
    with pytest.raises(CorpusInvalid):
        prepare_corpus(original, tmp_path, output)
    assert list(output.iterdir()) == [marker]
    assert marker.read_bytes() == b"preserve"


@pytest.mark.parametrize(
    "path", ["sources/0001.txt", "excerpts/0001.txt", "suite.json", "provenance.json"]
)
def test_tampered_files_cannot_verify(tmp_path, path):
    _, output, _ = prepared(tmp_path)
    (output / path).write_bytes(b"TAMPERED-PRIVATE-SOURCE")
    with pytest.raises(CorpusInvalid, match="^DOCUMENT_CORPUS_INVALID$"):
        verify_corpus(output)


@pytest.mark.parametrize(
    "change", ["annotation", "gold", "source_path", "entry_case", "suite_hash"]
)
def test_tampered_provenance_or_gold_cannot_verify(tmp_path, change):
    _, output, _ = prepared(tmp_path)
    path = output / "provenance.json"
    payload = json.loads(path.read_text("utf-8"))
    if change == "annotation":
        payload["manifest"]["cases"][0]["reviewer_note"] = "Changed annotation"
    elif change == "gold":
        payload["manifest"]["cases"][0]["gold"][0]["value"] = "1"
    elif change == "source_path":
        payload["entries"][0]["source_file"] = "../source.txt"
    elif change == "entry_case":
        payload["entries"][0]["case_id"] = "other"
    else:
        payload["suite_sha256"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CorpusInvalid):
        verify_corpus(output)


def test_changed_suite_case_metadata_cannot_verify(tmp_path):
    _, output, _ = prepared(tmp_path)
    path = output / "suite.json"
    payload = json.loads(path.read_text("utf-8"))
    payload["cases"][0]["classification"] = "public"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CorpusInvalid):
        verify_corpus(output)


@pytest.mark.parametrize(
    "raw", [b'{"schema_version":"1.0","schema_version":"1.0"}', b'{"x":NaN}', b'{"private":"\xff"}']
)
def test_verify_json_errors_are_stable_and_redacted(tmp_path, raw):
    _, output, _ = prepared(tmp_path)
    (output / "provenance.json").write_bytes(raw)
    with pytest.raises(CorpusInvalid, match="^DOCUMENT_CORPUS_INVALID$"):
        verify_corpus(output)


def test_metadata_urls_are_not_fetched_and_credentials_are_not_needed(tmp_path, monkeypatch):
    import socket

    def forbidden(*args, **kwargs):
        pytest.fail("Corpus preparation attempted network access")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setenv("GEMINI_API_KEY", "PRIVATE-CANARY")
    _, output, summary = prepared(tmp_path)
    assert verify_corpus(output) == summary
    assert "PRIVATE-CANARY" not in json.dumps(summary)

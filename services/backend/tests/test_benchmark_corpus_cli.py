"""Corpus preparation has no network side effects and refuses unsafe input/output."""

import json
import runpy
import sys
from pathlib import Path

import pytest
from test_benchmark_corpus import manifest

ROOT = Path(__file__).resolve().parents[3]


def invoke(monkeypatch, *arguments):
    module = runpy.run_path(str(ROOT / "scripts/prepare_document_benchmark.py"))
    monkeypatch.setattr(sys, "argv", ["prepare_document_benchmark.py", *map(str, arguments)])
    return module["main"]()


def input_manifest(tmp_path):
    model = manifest(tmp_path)
    path = tmp_path / "manifest.json"
    path.write_text(model.model_dump_json(), encoding="utf-8")
    return path


def test_prepare_and_verify_cli_print_only_counts_and_hashes(tmp_path, monkeypatch, capsys):
    source = input_manifest(tmp_path)
    target = tmp_path / "prepared"
    assert invoke(monkeypatch, "--manifest", source, "--output", target) == 0
    prepared = json.loads(capsys.readouterr().out)
    assert prepared["case_count"] == 1
    assert prepared["draft_annotations"] == 1
    assert prepared["model_called"] is False
    assert prepared["qualification_status"] == "not_qualified_offline"
    assert invoke(monkeypatch, "--verify", target) == 0
    assert json.loads(capsys.readouterr().out) == prepared
    assert "issuer" not in json.dumps(prepared)
    assert "source" not in json.dumps(prepared)


def test_existing_directory_is_never_overwritten(tmp_path, monkeypatch, capsys):
    source = input_manifest(tmp_path)
    target = tmp_path / "existing"
    target.mkdir()
    marker = target / "user-work.txt"
    marker.write_text("preserve", encoding="utf-8")
    assert invoke(monkeypatch, "--manifest", source, "--output", target) == 2
    assert marker.read_text() == "preserve"
    assert capsys.readouterr().out.strip() == '{"error_code":"DOCUMENT_CORPUS_INVALID"}'


@pytest.mark.parametrize("raw", [b'{"secret":"PRIVATE","secret":"LEAK"}', b'{"x":NaN}', b'"\xff"'])
def test_invalid_json_has_redacted_error(raw, tmp_path, monkeypatch, capsys):
    source = tmp_path / "secret-input.json"
    source.write_bytes(raw)
    assert invoke(monkeypatch, "--manifest", source, "--output", tmp_path / "output") == 2
    assert capsys.readouterr().out.strip() == '{"error_code":"DOCUMENT_CORPUS_INVALID"}'
    assert not (tmp_path / "output").exists()


def test_verify_detects_tampering_and_never_prints_changed_source(tmp_path, monkeypatch, capsys):
    source = input_manifest(tmp_path)
    target = tmp_path / "prepared"
    assert invoke(monkeypatch, "--manifest", source, "--output", target) == 0
    capsys.readouterr()
    next((target / "sources").iterdir()).write_bytes(b"PRIVATE changed source")
    assert invoke(monkeypatch, "--verify", target) == 2
    assert capsys.readouterr().out.strip() == '{"error_code":"DOCUMENT_CORPUS_INVALID"}'


def test_metadata_url_is_not_fetched(tmp_path, monkeypatch, capsys):
    import socket

    def forbidden(*args, **kwargs):
        pytest.fail("Corpus preparation attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    source = input_manifest(tmp_path)
    assert invoke(monkeypatch, "--manifest", source, "--output", tmp_path / "output") == 0
    assert json.loads(capsys.readouterr().out)["model_called"] is False


def test_manifest_requires_explicit_output(tmp_path, monkeypatch, capsys):
    source = input_manifest(tmp_path)
    assert invoke(monkeypatch, "--manifest", source) == 2
    assert capsys.readouterr().out.strip() == '{"error_code":"DOCUMENT_CORPUS_INVALID"}'

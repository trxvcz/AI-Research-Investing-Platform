"""CLI options are visible and cannot silently reuse a legacy packet identity."""

import hashlib
import json
import runpy
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[3]


def invoke(monkeypatch, *arguments):
    module = runpy.run_path(str(ROOT / "scripts/review_document.py"))
    monkeypatch.setattr(sys, "argv", ["review_document.py", *map(str, arguments)])
    return module["main"]()


def test_cli_keeps_legacy_identity_but_freezes_new_read_options(tmp_path, monkeypatch, capsys):
    raw = b"<table><tr><td>Revenue</td><td>281,724</td></tr></table>"
    source = tmp_path / "source.html"
    source.write_bytes(raw)
    assert invoke(monkeypatch, source, "--format", "html") == 0
    legacy = json.loads(capsys.readouterr().out)
    assert legacy["document_id"] == str(uuid5(NAMESPACE_URL, hashlib.sha256(raw).hexdigest()))
    assert "reader_version" not in legacy and "number_locale" not in legacy
    assert (
        invoke(
            monkeypatch,
            source,
            "--format",
            "html",
            "--reader-version",
            "table-text-v2",
            "--number-locale",
            "en-US",
        )
        == 0
    )
    modern = json.loads(capsys.readouterr().out)
    assert modern["document_id"] != legacy["document_id"]
    assert modern["reader_version"] == "table-text-v2"
    assert modern["number_locale"] == "en-US"
    assert modern["model_called"] is False
    assert modern["sha256"] == legacy["sha256"]


def test_cli_cannot_select_number_syntax_without_version(tmp_path, monkeypatch, capsys):
    source = tmp_path / "source.html"
    source.write_bytes(b"<p>Revenue 281,724 USD</p>")
    assert invoke(monkeypatch, source, "--format", "html", "--number-locale", "en-US") == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "blocked",
        "error_code": "DOCUMENT_REVIEW_FAILED",
    }

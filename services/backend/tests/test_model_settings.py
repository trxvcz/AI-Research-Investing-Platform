"""Local configuration never evaluates values or exposes secret text in errors."""

import os
from pathlib import Path

import pytest

from alphasense.model_settings import DOCUMENT_ENV_KEYS, MAX_ENV_BYTES, load_document_env


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", os.environ.copy())
    for key in DOCUMENT_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_allowlist_quotes_bom_and_no_evaluation(tmp_path: Path) -> None:
    path = tmp_path / "settings.env"
    path.write_text(
        '# local configuration\nexport GEMINI_API_KEY="$(do-not-execute)"\n'
        "ALPHASENSE_GEMINI_MODEL='gemini-test'\nUNKNOWN_DOCUMENT_SETTING=ignored\n"
        "GOOGLE_API_KEY=\n",
        encoding="utf-8-sig",
    )
    load_document_env(path)
    assert os.environ["GEMINI_API_KEY"] == "$(do-not-execute)"
    assert os.environ["ALPHASENSE_GEMINI_MODEL"] == "gemini-test"
    assert os.environ["GOOGLE_API_KEY"] == ""
    assert "UNKNOWN_DOCUMENT_SETTING" not in os.environ


def test_existing_process_value_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "process-secret")
    path = tmp_path / "settings.env"
    path.write_text("GEMINI_API_KEY=file-secret\n", encoding="utf-8")
    load_document_env(path)
    assert os.environ["GEMINI_API_KEY"] == "process-secret"


@pytest.mark.parametrize(
    "content",
    [
        "GEMINI_API_KEY=secret-value\nGEMINI_API_KEY=duplicate-secret",
        'GEMINI_API_KEY="secret-value',
        "GEMINI_API_KEY='secret-value\"",
        'GEMINI_API_KEY="secret"trailing"',
        "GEMINI_API_KEY=secret\x00value",
        "GEMINI_API_KEY=secret\u202evalue",
        "GEMINI_API_KEY=secret\x85value",
        "GEMINI_API_KEY=secret\tvalue",
    ],
)
def test_failures_are_redacted_and_atomic(tmp_path: Path, content: str) -> None:
    path = tmp_path / "settings.env"
    path.write_text("ALPHASENSE_GEMINI_MODEL=gemini-test\n" + content, encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        load_document_env(path)
    assert str(caught.value) == "Invalid document environment configuration"
    assert not any(key in os.environ for key in DOCUMENT_ENV_KEYS)


@pytest.mark.parametrize("raw", [b"x" * (MAX_ENV_BYTES + 1), b"GEMINI_API_KEY=\xff"])
def test_size_and_invalid_utf8_fail_closed(tmp_path: Path, raw: bytes) -> None:
    path = tmp_path / "settings.env"
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="^Invalid document environment configuration$"):
        load_document_env(path)


def test_missing_file_is_redacted(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="^Invalid document environment configuration$"):
        load_document_env(tmp_path / "secret-path.env")

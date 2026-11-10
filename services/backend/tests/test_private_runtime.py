"""Deployment secrets are bounded, redacted and never loaded from the main .env."""

import os
from pathlib import Path

import pytest

from alphasense import private_runtime as runtime


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", os.environ.copy())
    for name in (
        "ALPHASENSE_DATABASE_URL",
        "ALPHASENSE_DATABASE_URL_FILE",
        "ALPHASENSE_SEC_USER_AGENT",
        "ALPHASENSE_SEC_USER_AGENT_FILE",
    ):
        monkeypatch.delenv(name, raising=False)


def database_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: bytes) -> Path:
    path = tmp_path / "database-url.txt"
    path.write_bytes(raw)
    monkeypatch.setenv("ALPHASENSE_DATABASE_URL_FILE", str(path))
    return path


def test_required_secret_and_optional_empty_contact(tmp_path: Path, monkeypatch) -> None:
    value = "postgresql+psycopg://test:test-only@db/test"
    database_secret(tmp_path, monkeypatch, (value + "\r\n").encode())
    contact = tmp_path / "contact.txt"
    contact.write_bytes(b"")
    monkeypatch.setenv("ALPHASENSE_SEC_USER_AGENT_FILE", str(contact))
    monkeypatch.setenv("GEMINI_API_KEY", "do-not-touch-test-value")
    runtime.load_runtime_secrets()
    assert os.environ["ALPHASENSE_DATABASE_URL"] == value
    assert "ALPHASENSE_SEC_USER_AGENT" not in os.environ
    assert os.environ["GEMINI_API_KEY"] == "do-not-touch-test-value"


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"x" * 8193,
        b"\xff",
        b"postgresql+psycopg://hidden\x00value",
        b"postgresql+psycopg://hidden\nvalue",
        b"postgresql+psycopg://hidden\n\n",
        b" postgresql+psycopg://hidden",
        b"sqlite:///hidden",
    ],
)
def test_invalid_secret_is_redacted_and_does_not_change_environment(
    tmp_path, monkeypatch, raw
) -> None:
    database_secret(tmp_path, monkeypatch, raw)
    with pytest.raises(ValueError) as caught:
        runtime.load_runtime_secrets()
    assert str(caught.value) == "Invalid private runtime configuration"
    assert "ALPHASENSE_DATABASE_URL" not in os.environ


def test_ambiguous_or_missing_configuration_is_rejected(tmp_path, monkeypatch) -> None:
    with pytest.raises(ValueError, match="^Invalid private runtime configuration$"):
        runtime.load_runtime_secrets()
    database_secret(tmp_path, monkeypatch, b"postgresql+psycopg://test:test-only@db/test")
    monkeypatch.setenv("ALPHASENSE_DATABASE_URL", "do-not-expose")
    with pytest.raises(ValueError, match="^Invalid private runtime configuration$"):
        runtime.load_runtime_secrets()


def test_optional_invalid_contact_cannot_partially_install_database_secret(tmp_path, monkeypatch):
    database_secret(tmp_path, monkeypatch, b"postgresql+psycopg://test:test-only@db/test")
    contact = tmp_path / "contact.txt"
    contact.write_bytes(b"contact-secret\x00")
    monkeypatch.setenv("ALPHASENSE_SEC_USER_AGENT_FILE", str(contact))
    with pytest.raises(ValueError):
        runtime.load_runtime_secrets()
    assert "ALPHASENSE_DATABASE_URL" not in os.environ


@pytest.mark.parametrize("role", ["api", "sec-worker", "document-worker", "scheduler", "migrate"])
def test_role_executes_exact_command_after_loading_secret(tmp_path, monkeypatch, role):
    database_secret(tmp_path, monkeypatch, b"postgresql+psycopg://test:test-only@db/test")

    class ReplacedProcess(Exception):
        pass

    def execute(path, arguments):
        assert path == runtime.sys.executable
        assert arguments == [path, *runtime.ROLE_ARGUMENTS[role]]
        assert os.environ["ALPHASENSE_DATABASE_URL"].startswith("postgresql+psycopg://")
        raise ReplacedProcess

    monkeypatch.setattr(runtime.os, "execv", execute)
    with pytest.raises(ReplacedProcess):
        runtime.main([role])


def test_main_never_prints_secret_configuration(capsys, monkeypatch):
    monkeypatch.setenv("ALPHASENSE_DATABASE_URL_FILE", "missing-secret-path")
    assert runtime.main(["api"]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "Private runtime configuration or startup failed\n"


def test_api_role_disables_forwarded_headers_and_request_access_log():
    arguments = runtime.ROLE_ARGUMENTS["api"]
    assert "--no-proxy-headers" in arguments and "--no-access-log" in arguments
    assert "--factory" in arguments
    assert "migrate" not in arguments

"""Private host configuration cannot silently fall back to anonymous access."""

import hashlib
import json
from pathlib import Path

import pytest

from alphasense.private_settings import load_private_settings

TOKEN = "a" * 43


def configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "auth.json"
    path.write_text(
        json.dumps(
            {"username": "owner", "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest()}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHASENSE_PRIVATE_AUTH_FILE", str(path))
    monkeypatch.setenv("ALPHASENSE_PRIVATE_ORIGIN", "https://localhost:8443")
    return path


def test_configuration_is_explicit_and_hash_repr_is_redacted(tmp_path: Path, monkeypatch) -> None:
    configured(tmp_path, monkeypatch)
    settings = load_private_settings()
    assert settings.origin == "https://localhost:8443"
    assert settings.authority == "localhost:8443"
    assert settings.username == "owner"
    assert settings.token_sha256 not in repr(settings)


@pytest.mark.parametrize(
    "origin",
    [
        "",
        "http://localhost:8443",
        "https://owner:password@host",
        "https://host/",
        "https://host?secret=value",
        "https://host#secret",
        "https://HOST",
        "https://host:443",
        "https://host:",
        "https://host:99999",
        "https://host\n",
        "https://host..example",
        "https://-host.example",
        "https://host.example-",
        "https://host\\other",
    ],
)
def test_invalid_origins_fail_with_generic_error(tmp_path: Path, monkeypatch, origin: str) -> None:
    configured(tmp_path, monkeypatch)
    monkeypatch.setenv("ALPHASENSE_PRIVATE_ORIGIN", origin)
    with pytest.raises(ValueError) as error:
        load_private_settings()
    assert str(error.value) == "Invalid private access configuration"


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"x" * 4097,
        b"\xff",
        b"[]",
        b"{}",
        b'{"username":"owner","username":"duplicate","token_sha256":"secret"}',
        b'{"username":"owner","token_sha256":"secret","extra":"private"}',
        b'{"username":"private\\u0000value","token_sha256":"' + b"a" * 64 + b'"}',
        b'{"username":"private\\ud800value","token_sha256":"' + b"a" * 64 + b'"}',
        b'{"username":"owner","token_sha256":"' + b"A" * 64 + b'"}',
    ],
)
def test_invalid_secret_files_never_reflect_contents(
    tmp_path: Path, monkeypatch, raw: bytes
) -> None:
    path = configured(tmp_path, monkeypatch)
    path.write_bytes(raw)
    with pytest.raises(ValueError) as error:
        load_private_settings()
    assert str(error.value) == "Invalid private access configuration"


def test_missing_secret_configuration_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv("ALPHASENSE_PRIVATE_AUTH_FILE", raising=False)
    monkeypatch.setenv("ALPHASENSE_PRIVATE_ORIGIN", "https://localhost:8443")
    with pytest.raises(ValueError, match="^Invalid private access configuration$"):
        load_private_settings()

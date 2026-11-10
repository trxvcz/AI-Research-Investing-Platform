"""Private setup uses fresh high-entropy credentials and preserves existing files."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from alphasense.worker import current_git_sha

ROOT = Path(__file__).resolve().parents[3]


def test_secret_generation_is_exclusive_and_does_not_print_credentials(tmp_path: Path) -> None:
    target = tmp_path / "private"
    command = [
        sys.executable,
        str(ROOT / "scripts/create_private_secrets.py"),
        "--directory",
        str(target),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    token = (target / "owner-token.txt").read_text("utf-8").strip()
    password = (target / "postgres-password.txt").read_text("utf-8").strip()
    access = json.loads((target / "access.json").read_text("utf-8"))
    assert len(token) == 43 and len(password) == 43 and token != password
    assert access == {
        "username": "owner",
        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
    }
    assert (
        token not in result.stdout + result.stderr and password not in result.stdout + result.stderr
    )
    before = {p.name: p.read_bytes() for p in target.iterdir()}
    repeated = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert repeated.returncode == 1
    assert before == {p.name: p.read_bytes() for p in target.iterdir()}
    if os.name != "nt":
        assert target.stat().st_mode & 0o077 == 0
        assert (target / "owner-token.txt").stat().st_mode & 0o777 == 0o600
        assert all(
            path.stat().st_mode & 0o777 == 0o444
            for path in target.iterdir()
            if path.name != "owner-token.txt"
        )


def test_image_revision_does_not_require_git_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHASENSE_BUILD_GIT_SHA", "b" * 40)
    with patch("alphasense.worker.subprocess.run", side_effect=AssertionError("Unexpected git")):
        assert current_git_sha() == "b" * 40


@pytest.mark.parametrize("value", ["", "unknown", "b" * 39, "b" * 40 + "\n", "A" * 40])
def test_invalid_image_revision_fails_without_reflecting_value(monkeypatch, value: str) -> None:
    monkeypatch.setenv("ALPHASENSE_BUILD_GIT_SHA", value)
    with pytest.raises(ValueError, match="^Invalid build revision$"):
        current_git_sha()

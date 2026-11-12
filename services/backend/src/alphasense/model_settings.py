"""Explicit, bounded model settings import; values are never interpreted as code."""

import os
import unicodedata
from pathlib import Path

DOCUMENT_ENV_KEYS = frozenset({"GEMINI_API_KEY", "GOOGLE_API_KEY", "ALPHASENSE_GEMINI_MODEL"})
MAX_ENV_BYTES = 65536


def load_document_env(path: Path) -> None:
    """Load only model settings, preserving process values and redacting failures."""
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_ENV_BYTES + 1)
        if len(raw) > MAX_ENV_BYTES:
            raise ValueError("size")
        text = raw.decode("utf-8-sig", errors="strict")
        if any(unicodedata.category(char) in {"Cc", "Cf"} and char not in "\r\n" for char in text):
            raise ValueError("control")
        parsed: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            if name not in DOCUMENT_ENV_KEYS:
                continue
            if name in parsed:
                raise ValueError("duplicate")
            value = value.strip()
            if value.startswith(("'", '"')):
                quote = value[0]
                if len(value) < 2 or value[-1] != quote or quote in value[1:-1]:
                    raise ValueError("quote")
                value = value[1:-1]
            elif "'" in value or '"' in value:
                raise ValueError("quote")
            parsed[name] = value
    except (OSError, UnicodeError, ValueError):
        raise ValueError("Invalid document environment configuration") from None
    # Parse the entire file before changing the process environment.
    for name, value in parsed.items():
        os.environ.setdefault(name, value)

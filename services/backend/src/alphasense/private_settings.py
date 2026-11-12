"""Fail-closed private access configuration; errors never include secret material."""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class PrivateSettings:
    origin: str
    authority: str
    username: str
    token_sha256: str = field(repr=False)


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate configuration field")
        result[key] = value
    return result


def load_private_settings() -> PrivateSettings:
    try:
        origin = os.environ.get("ALPHASENSE_PRIVATE_ORIGIN", "")
        if not origin or any(not 33 <= ord(char) <= 126 for char in origin):
            raise ValueError("origin")
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.hostname is None
        ):
            raise ValueError("origin")
        host = parsed.hostname
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host):
            raise ValueError("host")
        if any(
            not part or len(part) > 63 or part.startswith("-") or part.endswith("-")
            for part in host.split(".")
        ):
            raise ValueError("host")
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("port")
        authority = host + (f":{port}" if port is not None and port != 443 else "")
        if origin != "https://" + authority:
            raise ValueError("canonical origin")
        source = os.environ.get("ALPHASENSE_PRIVATE_AUTH_FILE", "")
        if not source:
            raise ValueError("configuration")
        with Path(source).open("rb") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            raise ValueError("size")
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique)
        if not isinstance(data, dict) or set(data) != {"username", "token_sha256"}:
            raise ValueError("configuration")
        username, digest = data["username"], data["token_sha256"]
        if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", username):
            raise ValueError("username")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("digest")
        return PrivateSettings(origin, authority, username, digest)
    except (ValueError, TypeError, OSError, UnicodeError, RecursionError):
        raise ValueError("Invalid private access configuration") from None

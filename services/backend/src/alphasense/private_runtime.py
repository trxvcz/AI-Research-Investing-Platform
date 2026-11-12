"""Load mounted deployment secrets, then replace this process with one explicit role."""

import argparse
import os
import sys
import unicodedata
from pathlib import Path

MAX_SECRET_BYTES = 8192
ROLE_ARGUMENTS: dict[str, list[str]] = {
    "api": [
        "-m",
        "uvicorn",
        "alphasense.private_server:create_app",
        "--factory",
        "--host",
        "0.0.0.0",
        "--port",
        "8080",
        "--workers",
        "1",
        "--no-proxy-headers",
        "--no-server-header",
        "--no-access-log",
    ],
    "sec-worker": [
        "-m",
        "alphasense.task_worker",
        "--forever",
        "--worker-id",
        "private-sec-worker",
    ],
    "document-worker": [
        "-m",
        "alphasense.document_task_worker",
        "--forever",
        "--worker-id",
        "private-document-worker",
    ],
    "scheduler": [
        "-m",
        "alphasense.sec_scheduler",
        "--forever",
        "--worker-id",
        "private-sec-scheduler",
    ],
    "migrate": ["-m", "alembic", "upgrade", "head"],
}


def _secret_file(name: str, *, required: bool) -> str | None:
    path = os.environ.get(name + "_FILE")
    if os.environ.get(name) is not None:
        raise ValueError("Invalid private runtime configuration")
    if not path:
        if required:
            raise ValueError("Invalid private runtime configuration")
        return None
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_SECRET_BYTES + 1)
        if len(raw) > MAX_SECRET_BYTES:
            raise ValueError("size")
        value = raw.decode("utf-8", errors="strict")
        # Permit one conventional trailing newline, never arbitrary stripping.
        if value.endswith("\r\n"):
            value = value[:-2]
        elif value.endswith("\n"):
            value = value[:-1]
        if value != value.strip() or any(
            unicodedata.category(char) in {"Cc", "Cf"} for char in value
        ):
            raise ValueError("control")
        if not value:
            if required:
                raise ValueError("empty")
            return None
        return value
    except (OSError, UnicodeError, ValueError):
        raise ValueError("Invalid private runtime configuration") from None


def load_runtime_secrets() -> None:
    """Validate the whole configuration before changing process environment."""
    database = _secret_file("ALPHASENSE_DATABASE_URL", required=True)
    contact = _secret_file("ALPHASENSE_SEC_USER_AGENT", required=False)
    if database is None or not database.startswith("postgresql+psycopg://"):
        raise ValueError("Invalid private runtime configuration")
    os.environ["ALPHASENSE_DATABASE_URL"] = database
    if contact is not None:
        os.environ["ALPHASENSE_SEC_USER_AGENT"] = contact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=tuple(ROLE_ARGUMENTS))
    args = parser.parse_args(argv)
    try:
        load_runtime_secrets()
        os.execv(sys.executable, [sys.executable, *ROLE_ARGUMENTS[args.role]])
    except (OSError, ValueError):
        print("Private runtime configuration or startup failed", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

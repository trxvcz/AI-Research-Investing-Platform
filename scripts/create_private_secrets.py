"""Create new private-deployment secrets without printing or overwriting them."""

import argparse
import hashlib
import json
import os
import secrets
from pathlib import Path
from urllib.parse import quote


def create_secrets(directory: Path) -> None:
    # Never accept a partially initialized directory or replace existing secrets.
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    if os.name != "nt":
        os.chmod(directory, 0o700)
    token = secrets.token_urlsafe(32)
    database_password = secrets.token_urlsafe(32)
    values = {
        "access.json": json.dumps(
            {
                "username": "owner",
                "token_sha256": hashlib.sha256(token.encode("ascii")).hexdigest(),
            },
            indent=2,
        )
        + "\n",
        "owner-token.txt": token + "\n",
        "postgres-password.txt": database_password + "\n",
        "database-url.txt": "postgresql+psycopg://alphasense:"
        + quote(database_password, safe="")
        + "@db:5432/alphasense\n",
        "sec-user-agent.txt": "",
    }
    for name, value in values.items():
        descriptor = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(value)
        if os.name != "nt" and name != "owner-token.txt":
            # Compose file-backed secrets retain host ownership. Individual
            # read-only mounts must be readable by container UIDs, while the
            # host directory (0700) prevents access by other host users.
            os.chmod(directory / name, 0o444)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        create_secrets(args.directory)
    except OSError:
        print("Private settings creation failed; no existing files were replaced.")
        return 1
    print("Private settings created. Owner token is saved in owner-token.txt; keep it private.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Inspect a document or validate an agent draft; model calls require admitted policy."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from alphasense.db import StoreUnavailable, get_store
from alphasense.document_agent import run_agent, validate_draft
from alphasense.document_readers import read_text_document
from alphasense.model_settings import load_document_env
from alphasense.provider_policy import FreeOnlyGateway, ProviderDenied, load_policy
from alphasense.provider_quota import QuotaStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--format", choices=("text", "html", "xlsx", "pdf"), required=True)
    parser.add_argument(
        "--classification", choices=("public", "private", "secret"), default="private"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--draft", type=Path, help="Validate saved model JSON offline")
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--env-file", type=Path, help="Load only document-agent settings locally")
    args = parser.parse_args()
    try:
        if args.env_file:
            load_document_env(args.env_file)
        with args.file.open("rb") as stream:
            raw = stream.read(1048577)
        if len(raw) > 1048576:
            raise ValueError("Document too large")
        packet = read_text_document(
            raw,
            document_id=uuid5(NAMESPACE_URL, hashlib.sha256(raw).hexdigest()),
            classification=args.classification,
            format=args.format,
        )
        if args.draft:
            with args.draft.open("r", encoding="utf-8") as stream:
                draft = stream.read(1048577)
            if len(draft.encode("utf-8")) > 1048576:
                raise ValueError("Draft too large")
            result = validate_draft(packet, draft).model_dump(mode="json")
        elif args.live:
            from alphasense.gemini_transport import GeminiTransport

            provider_id = "gemini-document-extractor-v1"

            # Construction is lazy: admission must happen before reading credentials/network.
            def invoke(payload: object) -> str:
                return GeminiTransport(os.environ.get("ALPHASENSE_GEMINI_MODEL", ""))(payload)

            store = get_store()
            store.check_ready()
            gateway = FreeOnlyGateway(
                load_policy(), {provider_id: invoke}, QuotaStore(store.engine)
            )
            result = run_agent(packet, gateway, provider_id).model_dump(mode="json")
        else:
            result = {
                "status": "inspected",
                "document_id": str(packet.document_id),
                "sha256": packet.sha256,
                "format": packet.format,
                "classification": packet.classification,
                "blocks": len(packet.blocks),
                "model_called": False,
            }
        serialized = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(serialized)
        else:
            print(serialized, end="")
        return 2 if result["status"] in {"blocked", "rejected"} else 0
    except (OSError, ValueError, StoreUnavailable, ProviderDenied):
        print(json.dumps({"status": "blocked", "error_code": "DOCUMENT_REVIEW_FAILED"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

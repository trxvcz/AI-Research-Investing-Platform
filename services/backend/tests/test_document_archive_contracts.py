"""Point-in-time declarations and review concurrency have explicit boundaries."""

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from starlette.types import Message, Receive, Scope, Send

from alphasense.document_archive_contracts import DocumentArchiveCreate, DocumentReviewCommand
from alphasense.document_body_limit import (
    MAX_DOCUMENT_IMPORT_BODY,
    MAX_DOCUMENT_REVIEW_BODY,
    DocumentBodyLimit,
)


def create_payload() -> dict[str, Any]:
    return {
        "archive_id": str(uuid4()),
        "title": "Syntetyczny dokument",
        "format": "text",
        "content_base64": "YQ==",
        "draft_json": '{"schema_version":"1.0","facts":[]}',
        "source_available_at": "2026-01-01T10:00:00+01:00",
        "as_of": "2026-01-01T09:00:00Z",
    }


def test_equivalent_offsets_and_private_default() -> None:
    parsed = DocumentArchiveCreate.model_validate(create_payload())
    assert parsed.source_available_at == parsed.as_of
    assert parsed.classification == "private"


@pytest.mark.parametrize(
    "updates",
    [
        {"source_available_at": "2026-01-01T09:00:00.000001Z"},
        {"as_of": "2026-01-01"},
        {"as_of": 1767258000},
        {"title": "   "},
        {"format": "pdf"},
        {"api_key": "never-accepted"},
    ],
)
def test_invalid_or_future_availability_rejected(updates: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DocumentArchiveCreate.model_validate(create_payload() | updates)


@pytest.mark.parametrize("revision", [True, -1, 0.5, "0", 10001])
def test_review_revision_is_bounded_strict_integer(revision: object) -> None:
    with pytest.raises(ValidationError):
        DocumentReviewCommand.model_validate(
            {
                "command_id": str(uuid4()),
                "expected_revision": revision,
                "fact_index": 0,
                "verdict": "accepted",
                "note": "Sprawdzono cytat i znaczenie.",
            }
        )


@pytest.mark.parametrize(
    "path,limit",
    [
        ("/v1/panel/documents", MAX_DOCUMENT_IMPORT_BODY),
        (f"/v1/panel/documents/{uuid4()}/reviews/", MAX_DOCUMENT_REVIEW_BODY),
    ],
)
def test_chunked_document_is_bounded_before_json_or_storage(path: str, limit: int) -> None:
    async def run() -> list[Message]:
        sent: list[Message] = []
        chunks: list[Message] = [
            {"type": "http.request", "body": b"a" * limit, "more_body": True},
            {"type": "http.request", "body": b"x", "more_body": False},
        ]

        async def app(_scope: Scope, _receive: Receive, _send: Send) -> None:
            pytest.fail("Oversized request reached the application")

        async def receive() -> Message:
            return chunks.pop(0)

        async def send(message: Message) -> None:
            sent.append(message)

        scope: Scope = {
            "type": "http",
            "method": "POST",
            "path": path,
            "root_path": "",
        }
        await DocumentBodyLimit(app)(scope, receive, send)
        return sent

    sent = asyncio.run(run())
    assert sent[0]["status"] == 413

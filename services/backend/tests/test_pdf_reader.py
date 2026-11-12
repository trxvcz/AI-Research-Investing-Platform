"""Synthetic issuer-neutral PDFs and explicit bounded local-reader refusals."""

import io
import json
import subprocess

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    TextStringObject,
)

from alphasense import pdf_reader
from alphasense.pdf_reader import PDFReadError, read_pdf_blocks


def pdf(
    *pages: str | None, encrypted: bool = False, action: bool = False, compressed: bool = False
) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    reference = writer._add_object(font)
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        if text is not None:
            stream = DecodedStreamObject()
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii"))
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): reference})}
            )
            page[NameObject("/Contents")] = writer._add_object(
                stream.flate_encode() if compressed else stream
            )
    if encrypted:
        writer.encrypt("password")
    if action:
        writer._root_object[NameObject("/OpenAction")] = DictionaryObject(
            {
                NameObject("/S"): NameObject("/JavaScript"),
                NameObject("/JS"): TextStringObject("throw new Error('untrusted instruction');"),
            }
        )
    target = io.BytesIO()
    writer.write(target)
    return target.getvalue()


@pytest.mark.parametrize("issuer", ["Issuer A", "Different Issuer B"])
def test_same_reader_keeps_text_digits_pages_and_deterministic_order(issuer):
    raw = pdf(issuer + " revenue 12.5 million PLN", "Operating cash flow 1234 PLN")
    expected = [
        ("pdf:page:1:block:1", issuer + " revenue 12.5 million PLN"),
        ("pdf:page:2:block:1", "Operating cash flow 1234 PLN"),
    ]
    assert read_pdf_blocks(raw) == expected
    assert read_pdf_blocks(raw) == expected


def test_compressed_text_is_supported_without_any_model_or_network():
    assert read_pdf_blocks(pdf("Net income 42 USD", compressed=True)) == [
        ("pdf:page:1:block:1", "Net income 42 USD")
    ]


@pytest.mark.parametrize("raw", [b"garbage", b"%PDF-1.7\nbroken body"])
def test_malformed_pdf_returns_only_stable_code(raw):
    with pytest.raises(PDFReadError, match="^DOCUMENT_PDF_INVALID$"):
        read_pdf_blocks(raw)


def test_encrypted_pdf_refuses_even_if_no_password_was_supplied():
    with pytest.raises(PDFReadError, match="^DOCUMENT_PDF_ENCRYPTED$"):
        read_pdf_blocks(pdf("Revenue 100", encrypted=True))


@pytest.mark.parametrize("pages", [(None,), ("Revenue 100", None), (None, "Revenue 100")])
def test_empty_or_image_only_page_rejects_whole_document(pages):
    with pytest.raises(PDFReadError, match="^DOCUMENT_PDF_TEXT_REQUIRED$"):
        read_pdf_blocks(pdf(*pages))


def test_javascript_is_refused_without_execution():
    with pytest.raises(PDFReadError, match="^DOCUMENT_PDF_UNSAFE$"):
        read_pdf_blocks(pdf("Revenue 100", action=True))


@pytest.mark.parametrize("kind", ["attachment", "form", "link", "unknown-filter"])
def test_active_or_unhandled_structures_are_refused(kind):
    writer = PdfWriter(clone_from=io.BytesIO(pdf("Revenue 100")))
    if kind == "attachment":
        writer.add_attachment("hidden.txt", b"untrusted")
    elif kind == "form":
        writer._root_object[NameObject("/AcroForm")] = DictionaryObject()
    elif kind == "link":
        writer.pages[0][NameObject("/AA")] = DictionaryObject(
            {
                NameObject("/O"): DictionaryObject(
                    {
                        NameObject("/S"): NameObject("/URI"),
                        NameObject("/URI"): TextStringObject("https://untrusted.invalid"),
                    }
                )
            }
        )
    else:
        stream = writer.pages[0]["/Contents"]
        stream[NameObject("/Filter")] = NameObject("/UnknownDecode")
    target = io.BytesIO()
    writer.write(target)
    with pytest.raises(PDFReadError, match="^DOCUMENT_PDF_UNSAFE$"):
        read_pdf_blocks(target.getvalue())


def test_page_count_limit_is_not_silent_truncation():
    with pytest.raises(PDFReadError, match="^DOCUMENT_PDF_LIMIT$"):
        read_pdf_blocks(pdf(*(["Revenue 100"] * 101)))


def test_large_text_line_is_refused_without_splitting_numeric_tokens():
    with pytest.raises(PDFReadError, match="^DOCUMENT_PDF_LIMIT$"):
        read_pdf_blocks(pdf("1" * 32769))


def test_compression_bomb_cannot_bypass_decoded_stream_limit():
    raw = pdf(" " * (pdf_reader.MAX_STREAM_BYTES + 1), compressed=True)
    assert len(raw) < pdf_reader.MAX_RAW
    with pytest.raises(PDFReadError, match="^DOCUMENT_PDF_LIMIT$"):
        read_pdf_blocks(raw)


def test_excessive_block_count_rejects_whole_document():
    with pytest.raises(PDFReadError, match="^DOCUMENT_PDF_LIMIT$"):
        read_pdf_blocks(pdf("\n".join(["Revenue 100"] * 513)))


@pytest.mark.parametrize("raw", [b"", b"%PDF-" + b"x" * 1048576])
def test_input_size_rejected_before_process(raw, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Out-of-bounds input must not spawn a worker")

    monkeypatch.setattr(pdf_reader.subprocess, "run", forbidden)
    with pytest.raises(PDFReadError, match="^DOCUMENT_PDF_LIMIT$"):
        read_pdf_blocks(raw)


def test_timeout_is_stable_and_subprocess_run_owns_kill_and_reap(monkeypatch):
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == pdf_reader.TIMEOUT_SECONDS
        raise subprocess.TimeoutExpired("untrusted document", 8)

    monkeypatch.setattr(pdf_reader.subprocess, "run", timeout)
    with pytest.raises(PDFReadError, match="^DOCUMENT_PDF_LIMIT$"):
        read_pdf_blocks(pdf("Revenue 100"))


def test_actual_timeout_terminates_and_reaps_child(monkeypatch):
    processes = []
    original = pdf_reader.subprocess.Popen

    def tracked(*args, **kwargs):
        child = original(*args, **kwargs)
        processes.append(child)
        return child

    monkeypatch.setattr(pdf_reader.subprocess, "Popen", tracked)
    monkeypatch.setattr(pdf_reader, "TIMEOUT_SECONDS", 0.001)
    with pytest.raises(PDFReadError, match="^DOCUMENT_PDF_LIMIT$"):
        read_pdf_blocks(pdf("Revenue 100"))
    assert len(processes) == 1
    assert processes[0].poll() is not None


def test_process_does_not_inherit_credentials_or_python_settings(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-private-key")
    monkeypatch.setenv("ALPHASENSE_DATABASE_URL", "synthetic-database-secret")
    monkeypatch.setenv("PYTHONPATH", "untrusted-python-directory")
    original = pdf_reader.subprocess.run

    def inspected(*args, **kwargs):
        assert set(kwargs["env"]) <= {"SystemRoot", "WINDIR"}
        assert args[0][1] == "-I"
        assert kwargs["close_fds"] is True
        assert kwargs["stderr"] == subprocess.DEVNULL
        return original(*args, **kwargs)

    monkeypatch.setattr(pdf_reader.subprocess, "run", inspected)
    assert read_pdf_blocks(pdf("Revenue 100"))[0][1] == "Revenue 100"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"error": "private parser text"},
        {"blocks": []},
        {"blocks": [["loc", ""]]},
        {"blocks": [["loc", "text", "extra"]]},
        {"blocks": [["loc", 1]]},
    ],
)
def test_invalid_worker_response_is_never_trusted(payload, monkeypatch):
    def invalid(*args, **kwargs):
        return subprocess.CompletedProcess([], 0, json.dumps(payload).encode())

    monkeypatch.setattr(pdf_reader.subprocess, "run", invalid)
    with pytest.raises(PDFReadError, match="^DOCUMENT_PDF_INVALID$"):
        read_pdf_blocks(pdf("Revenue 100"))


def test_memory_limit_failure_is_fail_closed(monkeypatch, capsys):
    def fail():
        raise OSError("private system information")

    monkeypatch.setattr(pdf_reader, "_memory_limit", fail)
    monkeypatch.setattr(pdf_reader.logging, "disable", lambda level: None)
    pdf_reader._worker()
    assert capsys.readouterr().out == '{"error":"DOCUMENT_PDF_UNAVAILABLE"}'


def test_orphaned_active_object_is_also_rejected():
    writer = PdfWriter(clone_from=io.BytesIO(pdf("Revenue 100")))
    writer._add_object(DictionaryObject({NameObject("/JS"): TextStringObject("ignored()")}))
    target = io.BytesIO()
    writer.write(target)
    with pytest.raises(PDFReadError, match="^DOCUMENT_PDF_UNSAFE$"):
        read_pdf_blocks(target.getvalue())


def test_cyclic_object_graph_terminates():
    writer = PdfWriter(clone_from=io.BytesIO(pdf("Revenue 100")))
    node = DictionaryObject()
    ref = writer._add_object(node)
    node[NameObject("/Cycle")] = ArrayObject([ref])
    writer._root_object[NameObject("/Extra")] = ref
    target = io.BytesIO()
    writer.write(target)
    assert read_pdf_blocks(target.getvalue())[0][1] == "Revenue 100"

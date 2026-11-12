"""Read a bounded PDF text layer in a resource-limited local child process."""

import io
import json
import logging
import os
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Any

MAX_RAW = 1048576
MAX_PAGES = 100
MAX_BLOCKS = 512
MAX_BLOCK_CHARS = 32768
MAX_TEXT_BYTES = 2097152
MAX_STREAM_BYTES = 8388608
MAX_MEMORY_BYTES = 512 * 1024 * 1024
TIMEOUT_SECONDS = 8
MAX_RESPONSE_BYTES = 13 * 1024 * 1024
ERROR_CODES = frozenset(
    {
        "DOCUMENT_PDF_INVALID",
        "DOCUMENT_PDF_ENCRYPTED",
        "DOCUMENT_PDF_UNSAFE",
        "DOCUMENT_PDF_LIMIT",
        "DOCUMENT_PDF_TEXT_REQUIRED",
        "DOCUMENT_PDF_UNAVAILABLE",
    }
)


class PDFReadError(ValueError):
    """Stable refusal without source bytes or parser diagnostic text."""


def _memory_limit() -> object:
    """Fail closed if the OS cannot enforce a per-process memory limit."""
    if sys.platform.startswith("linux"):
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY_BYTES, MAX_MEMORY_BYTES))
        resource.setrlimit(resource.RLIMIT_CPU, (6, 6))
        return None
    if os.name != "nt":
        raise OSError("Unsupported resource limit platform")

    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IOCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_uint64)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits),
            ("IoInfo", IOCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise OSError("Resource limit unavailable")
    limits = ExtendedLimits()
    # PROCESS_MEMORY + KILL_ON_JOB_CLOSE. Keep the handle alive until process exit.
    limits.BasicLimitInformation.LimitFlags = 0x100 | 0x2000
    limits.ProcessMemoryLimit = MAX_MEMORY_BYTES
    if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        kernel.CloseHandle(handle)
        raise OSError("Resource limit unavailable")
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        kernel.CloseHandle(handle)
        raise OSError("Resource limit unavailable")
    return handle


def _extract(raw: bytes) -> list[tuple[str, str]]:
    # Imported only after limits are active in the worker process.
    import pypdf
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, StreamObject

    pypdf.overwrite_configuration(
        maximum_declared_stream_length=MAX_STREAM_BYTES,
        array_based_stream_maximum_output_length=MAX_STREAM_BYTES,
        zlib_maximum_output_length=MAX_STREAM_BYTES,
        lzw_maximum_output_length=MAX_STREAM_BYTES,
        run_length_maximum_output_length=MAX_STREAM_BYTES,
        image_maximum_buffer_size=MAX_STREAM_BYTES,
        stream_decoding_work_maximum_length=MAX_STREAM_BYTES,
        page_tree_maximum_entries=1000,
        page_tree_maximum_depth=32,
        page_tree_maximum_page_entries=10000,
        array_maximum_element_count=10000,
        dictionary_maximum_element_count=10000,
        stream_parsing_work_maximum_count=100000,
        xform_maximum_invocations_per_extraction=100,
        stream_filters_maximum_length=4,
        jbig2dec_binary=None,
    )
    reader = pypdf.PdfReader(
        io.BytesIO(raw),
        strict=True,
        root_object_recovery_limit=0,
        xref_stream_maximum_entries=10000,
    )
    if reader.is_encrypted:
        raise PDFReadError("DOCUMENT_PDF_ENCRYPTED")

    forbidden = {
        "/OpenAction",
        "/AA",
        "/A",
        "/JS",
        "/JavaScript",
        "/Launch",
        "/EmbeddedFiles",
        "/EF",
        "/AcroForm",
        "/XFA",
        "/RichMediaContent",
        "/RichMediaSettings",
        "/SubmitForm",
        "/ImportData",
        "/Collection",
        "/Sound",
        "/Movie",
        "/3DD",
    }
    allowed_filters = {
        "/FlateDecode",
        "/ASCIIHexDecode",
        "/ASCII85Decode",
        "/RunLengthDecode",
        "/LZWDecode",
        "/DCTDecode",
        "/JPXDecode",
        "/CCITTFaxDecode",
    }
    stack: list[Any] = [reader.trailer]
    for generation, offsets in reader.xref.items():
        if generation == 65535:
            continue
        stack.extend(IndirectObject(number, generation, reader) for number in offsets if number)
    stack.extend(IndirectObject(number, 0, reader) for number in reader.xref_objStm)
    if len(stack) > 10000:
        raise PDFReadError("DOCUMENT_PDF_LIMIT")
    visited: set[tuple[int, int] | int] = set()
    examined = 0
    while stack:
        examined += 1
        if examined > 50000:
            raise PDFReadError("DOCUMENT_PDF_LIMIT")
        obj = stack.pop()
        if isinstance(obj, IndirectObject):
            identity: tuple[int, int] | int = (obj.idnum, obj.generation)
            if identity in visited:
                continue
            visited.add(identity)
            stack.append(obj.get_object())
        elif isinstance(obj, DictionaryObject):
            if id(obj) in visited:
                continue
            visited.add(id(obj))
            if forbidden.intersection(obj.keys()) or obj.get("/Type") in {
                "/Filespec",
                "/EmbeddedFile",
                "/Action",
            }:
                raise PDFReadError("DOCUMENT_PDF_UNSAFE")
            if isinstance(obj, StreamObject):
                if "/F" in obj:
                    raise PDFReadError("DOCUMENT_PDF_UNSAFE")
                filters = obj.get("/Filter", [])
                if not isinstance(filters, ArrayObject | list):
                    filters = [filters]
                if len(filters) > 4 or any(str(item) not in allowed_filters for item in filters):
                    raise PDFReadError("DOCUMENT_PDF_UNSAFE")
            stack.extend(obj.values())
        elif isinstance(obj, ArrayObject):
            stack.extend(obj)

    page_count = len(reader.pages)
    if not 1 <= page_count <= MAX_PAGES:
        raise PDFReadError("DOCUMENT_PDF_LIMIT")
    result: list[tuple[str, str]] = []
    total_text = total_stream = 0
    for number, page in enumerate(reader.pages, 1):
        content = page.get_contents()
        if content is not None:
            total_stream += len(content.get_data())
        if total_stream > MAX_STREAM_BYTES:
            raise PDFReadError("DOCUMENT_PDF_LIMIT")
        text = page.extract_text(extraction_mode="plain")
        if not text or not text.strip():
            raise PDFReadError("DOCUMENT_PDF_TEXT_REQUIRED")
        if "\x00" in text:
            raise PDFReadError("DOCUMENT_PDF_INVALID")
        # Preserve extractor order and numeric tokens; do not guess table semantics.
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for block_number, line in enumerate(lines, 1):
            total_text += len(line.encode("utf-8"))
            if (
                len(line) > MAX_BLOCK_CHARS
                or total_text > MAX_TEXT_BYTES
                or len(result) >= MAX_BLOCKS
            ):
                raise PDFReadError("DOCUMENT_PDF_LIMIT")
            result.append((f"pdf:page:{number}:block:{block_number}", line))
    return result


def _worker_command() -> list[str]:
    module = str(Path(__file__).resolve())
    if os.name != "nt":
        return [sys.executable, "-I", module, "--worker"]
    # Windows venv python.exe is a redirector which spawns another process.
    # Killing that launcher on timeout can leave the parser running. Launch
    # the actual interpreter and add only this environment's trusted packages.
    executable = getattr(sys, "_base_executable", None)
    if not isinstance(executable, str) or not Path(executable).is_file():
        raise OSError("Direct interpreter unavailable")
    bootstrap = (
        "import sys,runpy; sys.path.insert(0,sys.argv[1]); "
        "module=sys.argv[2]; sys.argv=[module,'--worker']; "
        "runpy.run_path(module,run_name='__main__')"
    )
    return [executable, "-I", "-c", bootstrap, sysconfig.get_path("purelib"), module]


def read_pdf_blocks(raw: bytes) -> list[tuple[str, str]]:
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_RAW:
        raise PDFReadError("DOCUMENT_PDF_LIMIT")
    if not raw.startswith(b"%PDF-"):
        raise PDFReadError("DOCUMENT_PDF_INVALID")
    # Do not pass API keys, database URLs, PYTHONPATH or user Python settings.
    environment = {
        name: os.environ[name] for name in ("SystemRoot", "WINDIR") if name in os.environ
    }
    try:
        process = subprocess.run(
            _worker_command(),
            input=raw,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=TIMEOUT_SECONDS,
            env=environment,
            check=False,
            close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired:
        # subprocess.run kills and reaps the child before raising TimeoutExpired.
        raise PDFReadError("DOCUMENT_PDF_LIMIT") from None
    except OSError:
        raise PDFReadError("DOCUMENT_PDF_UNAVAILABLE") from None
    if process.returncode != 0:
        raise PDFReadError("DOCUMENT_PDF_LIMIT")
    try:
        if len(process.stdout) > MAX_RESPONSE_BYTES:
            raise ValueError("response size")
        response = json.loads(process.stdout)
        if type(response) is not dict:
            raise ValueError("response type")
        if set(response) == {"error"} and response["error"] in ERROR_CODES:
            raise PDFReadError(response["error"])
        if set(response) != {"blocks"} or type(response["blocks"]) is not list:
            raise ValueError("response structure")
        blocks = response["blocks"]
        if not 1 <= len(blocks) <= MAX_BLOCKS:
            raise ValueError("response count")
        result = []
        total = 0
        for item in blocks:
            if (
                type(item) is not list
                or len(item) != 2
                or any(type(value) is not str for value in item)
            ):
                raise ValueError("response block")
            locator, text = item
            if not text.strip() or len(text) > MAX_BLOCK_CHARS or "\x00" in text:
                raise ValueError("response text")
            total += len(text.encode("utf-8"))
            if total > MAX_TEXT_BYTES:
                raise ValueError("response text size")
            result.append((locator, text))
        return result
    except PDFReadError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise PDFReadError("DOCUMENT_PDF_INVALID") from None


def _worker() -> None:
    logging.disable(logging.CRITICAL)
    try:
        # Retain the Windows Job handle until process exit.
        job_handle = _memory_limit()
    except (OSError, ValueError, ImportError):
        sys.stdout.write('{"error":"DOCUMENT_PDF_UNAVAILABLE"}')
        return
    try:
        raw = sys.stdin.buffer.read(MAX_RAW + 1)
        if not 1 <= len(raw) <= MAX_RAW or not raw.startswith(b"%PDF-"):
            raise PDFReadError("DOCUMENT_PDF_INVALID")
        response: dict[str, object] = {"blocks": _extract(raw)}
    except PDFReadError as error:
        response = {"error": str(error)}
    except MemoryError:
        response = {"error": "DOCUMENT_PDF_LIMIT"}
    except ImportError:
        response = {"error": "DOCUMENT_PDF_UNAVAILABLE"}
    except Exception as error:
        # Parser errors can contain source text, filenames, URIs and object data.
        response = {
            "error": "DOCUMENT_PDF_LIMIT"
            if type(error).__name__ == "LimitReachedError"
            else "DOCUMENT_PDF_INVALID"
        }
    sys.stdout.write(json.dumps(response, ensure_ascii=True, separators=(",", ":")))
    _ = job_handle


if __name__ == "__main__" and sys.argv[1:] == ["--worker"]:
    _worker()

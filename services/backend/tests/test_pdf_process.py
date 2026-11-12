"""Timeout must terminate the actual interpreter, including Windows venv launchers."""

import subprocess
from pathlib import Path

import pytest

from alphasense import pdf_reader


def test_timeout_reaps_the_process_that_actually_reads_the_document(tmp_path, monkeypatch):
    marker = tmp_path / "actual-pid.txt"
    worker = tmp_path / "sleeping-reader.py"
    worker.write_text(
        "import os,time,pathlib\n"
        f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    processes = []
    original = subprocess.Popen

    def tracked(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(pdf_reader, "__file__", str(worker))
    monkeypatch.setattr(pdf_reader, "TIMEOUT_SECONDS", 1.5)
    monkeypatch.setattr(subprocess, "Popen", tracked)
    with pytest.raises(pdf_reader.PDFReadError, match="^DOCUMENT_PDF_LIMIT$"):
        pdf_reader.read_pdf_blocks(b"%PDF-1.7\nsynthetic timeout probe")
    assert len(processes) == 1
    # poll() alone would only prove that a venv redirector had exited.
    assert int(marker.read_text()) == processes[0].pid
    assert processes[0].poll() is not None


def test_worker_command_uses_only_an_existing_interpreter_and_module():
    command = pdf_reader._worker_command()
    assert Path(command[0]).is_file()
    assert command[1] == "-I"
    assert str(Path(pdf_reader.__file__).resolve()) in command

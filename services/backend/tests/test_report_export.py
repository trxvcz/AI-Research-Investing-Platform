"""HTML export escapes source text and preserves existing immutable artifacts."""

from pathlib import Path

import pytest
from test_store import sample

from alphasense.report_contracts import ReportContent, seal_report
from alphasense.report_export import export_report, report_html


def test_source_html_is_displayed_as_text_and_missing_is_not_zero(tmp_path: Path) -> None:
    data = sample().model_dump(mode="python", exclude={"checksum", "input_sha256"})
    data["limitations"] = ['<script>alert("source")</script>']
    report = seal_report(ReportContent.model_validate(data))
    html = report_html(report)
    assert f"<h1>{report.input.instrument_id}</h1>" in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "Content-Security-Policy" in html and "default-src 'none'" in html
    assert "brak" in html and "0.0" in html
    paths = export_report(report, tmp_path)
    assert paths[0].read_bytes().endswith(b"\n")
    assert paths[1].read_text(encoding="utf-8") == html
    assert export_report(report, tmp_path) == paths


def test_existing_artifact_is_never_overwritten(tmp_path: Path) -> None:
    report = sample()
    paths = export_report(report, tmp_path)
    paths[1].write_text("existing user artifact", encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to overwrite"):
        export_report(report, tmp_path)
    assert paths[1].read_text(encoding="utf-8") == "existing user artifact"

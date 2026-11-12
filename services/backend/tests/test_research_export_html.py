"""Portable HTML preserves exact selected evidence and treats all source text as data."""

from html.parser import HTMLParser

import pytest
from test_research_export import export_fixture

from alphasense.ai_analysis_contracts import AiAnalysisRecord, AiNarrative
from alphasense.report_contracts import ReportContent, seal_report
from alphasense.research_export import build_research_export
from alphasense.research_export_html import HTML_CSP, _link, render_research_export_html


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def parse(document):
    result = Elements()
    result.feed(document)
    return result


@pytest.mark.parametrize("version", [None, "v1", "v2"])
def test_standalone_export_is_deterministic_inert_and_selected(version):
    bundle = build_research_export(*export_fixture(version))
    document = render_research_export_html(bundle)
    assert render_research_export_html(bundle) == document
    parsed = parse(document)
    assert document.startswith('<!doctype html><html lang="pl">')
    assert not {tag for tag, _ in parsed.elements} & {"script", "iframe", "img", "form", "link"}
    assert all(not name.startswith("on") for _, attrs in parsed.elements for name in attrs)
    assert any(
        attrs.get("http-equiv") == "Content-Security-Policy" and attrs["content"] == HTML_CSP
        for _, attrs in parsed.elements
    )
    assert str(bundle.report.input.instrument_id) in document
    assert bundle.checksum in document and bundle.report.checksum in document
    assert "Suma kontrolna nie jest podpisem autentyczności" in document
    if version is None:
        assert "Nie wybrano zapisanej analizy AI" in document
    else:
        assert str(bundle.ai_analysis.request_id) in document
        assert bundle.ai_analysis.model_id in document
        assert bundle.ai_analysis.prompt_version in document


def test_history_claim_cites_frozen_previous_current_delta_and_source():
    report, ratios, ai = export_fixture("v2")
    document = render_research_export_html(build_research_export(report, ratios, ai))
    text = " ".join(parse(document).text)
    assert "Przychód: 120 USD" in text and "Przychód: 150 USD" in text
    assert "Zmiana wartości: 30 USD" in text
    assert "Zmiana r/r: 25.000000%" in text
    assert "2024-01-01T00:00:00+00:00" in text
    assert ai.evidence_context.context_sha256 in text
    assert ai.evidence_context.evidence[0].source.sha256 in text


def test_no_ai_still_includes_all_current_observations_and_explicit_missing_reason():
    report, ratios, _ = export_fixture()
    document = render_research_export_html(build_research_export(report, ratios))
    assert "Dane finansowe raportu" in document
    assert "150 USD" in document
    missing = report.input.observations[1]
    assert missing.status == "missing"
    assert missing.reason in " ".join(parse(document).text)
    assert "Nie wyliczono — missing:" in document
    assert str(ratios.history.series[0].points[0].filing_date) in document
    assert "NO_PRIOR_PERIOD" in document
    assert "Nie wyliczono: MISSING_INPUT" in document


def test_untrusted_ai_and_license_are_text_not_active_html():
    report, ratios, ai = export_fixture("v1")
    raw = ai.model_dump(mode="python")
    attack = '<script>alert("x")</script><img src=x onerror=alert(1)>'
    raw["analysis"] = AiNarrative(
        summary=[{"text": attack, "observation_indexes": [0]}],
        strengths=[],
        risks=[],
        questions=[],
        limitations=[attack],
    )
    ai = AiAnalysisRecord.model_validate(raw)
    document = render_research_export_html(build_research_export(report, ratios, ai))
    assert attack in " ".join(parse(document).text)
    assert "<script>" not in document and "<img " not in document
    assert "&lt;script&gt;" in document

    content = report.model_dump(mode="python", exclude={"checksum", "input_sha256"})
    content["sources"][0]["license"] = attack
    changed = seal_report(ReportContent.model_validate(content))
    history = ratios.history.model_copy(update={"report_checksum": changed.checksum})
    from alphasense.financial_ratios import build_financial_ratios

    document = render_research_export_html(
        build_research_export(changed, build_financial_ratios(history))
    )
    assert attack in " ".join(parse(document).text)
    assert "<script>" not in document


@pytest.mark.parametrize(
    "url",
    [
        'javascript:alert("x")',
        "https://evil.example/report",
        "https://data.sec.gov.evil.example/report",
        "https://user:secret@data.sec.gov/report",
        "https://data.sec.gov/report?private=1",
        "https://www.sec.gov/report#fragment",
        "https://data.sec.gov:444/report",
        "https://data.sec.gov:bad/report",
    ],
)
def test_unapproved_urls_have_no_clickable_link(url):
    document = _link(url)
    assert not any(tag == "a" for tag, _ in parse(document).elements)
    assert url in "".join(parse(document).text)


def test_only_official_https_links_are_clickable_and_no_active_resources():
    for url in ("https://data.sec.gov/report", "https://www.sec.gov/report"):
        parsed = parse(_link(url))
        assert parsed.elements == [("a", {"href": url, "rel": "noreferrer"})]


def test_renderer_revalidates_mutable_bundle_checksum():
    bundle = build_research_export(*export_fixture())
    bundle.limitations.append("Changed after sealing")
    with pytest.raises(ValueError, match="Export checksum mismatch"):
        render_research_export_html(bundle)

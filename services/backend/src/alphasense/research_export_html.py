"""Inert, self-contained reading copy of an explicitly selected research bundle."""

from html import escape
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from alphasense.ai_analysis_contracts import AiNarrative
from alphasense.ai_history_contracts import AiHistoryFact, AiHistoryNarrative
from alphasense.contracts import AvailableObservation
from alphasense.report_contracts import SourceProvenance

if TYPE_CHECKING:
    from alphasense.research_export import ResearchExport

HTML_CSP = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
_METRICS = {
    "revenue": "Przychód",
    "net_income": "Wynik netto",
    "operating_cash_flow": "Przepływy operacyjne",
    "capital_expenditures": "Nakłady na rzeczowe aktywa trwałe",
    "cash_and_equivalents": "Gotówka i ekwiwalenty",
    "long_term_debt_current": "Dług długoterminowy — część bieżąca",
    "long_term_debt_noncurrent": "Dług długoterminowy — część niebieżąca",
    "net_margin": "Marża netto",
    "operating_cash_flow_margin": "Przepływy operacyjne / przychody",
    "capex_to_revenue": "Nakłady / przychody",
    "free_cash_flow_margin": "(Przepływy operacyjne − nakłady) / przychody",
}


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _metric(value: str) -> str:
    return _e(_METRICS.get(value, value))


def _list(values: list[str]) -> str:
    return "<ul>" + "".join("<li>" + _e(value) + "</li>" for value in values) + "</ul>"


def _link(raw: object) -> str:
    if raw is None:
        return "Brak URL"
    value = str(raw)
    try:
        parsed = urlsplit(value)
        safe = (
            parsed.scheme == "https"
            and parsed.hostname in {"data.sec.gov", "www.sec.gov"}
            and parsed.port in {None, 443}
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        safe = False
    return (
        '<a href="' + _e(value) + '" rel="noreferrer">' + _e(value) + "</a>" if safe else _e(value)
    )


def _source(source: SourceProvenance) -> str:
    return (
        "<p>Źródło: "
        + _e(source.source_id)
        + " · snapshot "
        + _e(source.snapshot_id)
        + "<br>SHA-256: <code>"
        + _e(source.sha256)
        + "</code><br>"
        + _link(source.url)
        + "<br>Dostępne od "
        + _e(source.retrieved_at.isoformat())
        + "<br>Warunki źródła: "
        + _e(source.license)
        + "</p>"
    )


def _fact(fact: AiHistoryFact) -> str:
    return (
        "<p><strong>"
        + _metric(fact.metric)
        + ": "
        + _e(fact.value)
        + " "
        + _e(fact.currency or fact.unit)
        + "</strong><br>Okres: "
        + _e(fact.period_start.isoformat())
        + " – "
        + _e(fact.period_end.isoformat())
        + "<br>Dostępne od "
        + _e(fact.available_at.isoformat())
        + "<br>Sprawozdanie: "
        + _e(fact.filing_accession or "Nieustalone")
        + "</p>"
        + _source(fact.source)
    )


def _observation(bundle: "ResearchExport", index: int) -> str:
    observation = bundle.report.input.observations[index]
    if not isinstance(observation, AvailableObservation):
        raise ValueError("Unavailable AI evidence")
    source = next(
        source
        for source in bundle.report.sources
        if (source.source_id, source.snapshot_id)
        == (observation.source_id, observation.snapshot_id)
    )
    return (
        "<p><strong>"
        + _metric(observation.metric)
        + ": "
        + _e(observation.value)
        + " "
        + _e(observation.currency or observation.unit)
        + "</strong><br>Okres: "
        + _e(observation.period_start.isoformat())
        + " – "
        + _e(observation.period_end.isoformat())
        + "<br>Dostępne od "
        + _e(observation.available_at.isoformat())
        + "</p>"
        + _source(source)
    )


def _ai(bundle: "ResearchExport") -> str:
    record = bundle.ai_analysis
    if record is None:
        return "<h2>Analiza AI</h2><p>Nie wybrano zapisanej analizy AI do tego eksportu.</p>"
    narrative = record.analysis
    result = (
        "<h2>Analiza AI</h2><p>Wybrana zapisana odpowiedź; eksport nie wywołuje modelu. "
        "Interpretację należy sprawdzić.</p><p>Żądanie: "
        + _e(record.request_id)
        + "<br>Model: "
        + _e(record.model_id)
        + "<br>Wersja instrukcji: "
        + _e(record.prompt_version)
        + "<br>Zakończono: "
        + _e(record.finished_at)
        + "</p>"
    )
    for name, title in (
        ("summary", "Najważniejsze wnioski"),
        ("strengths", "Mocne strony"),
        ("risks", "Ryzyka"),
        ("questions", "Co warto sprawdzić"),
    ):
        result += "<h3>" + title + "</h3>"
        if isinstance(narrative, AiNarrative):
            claims = getattr(narrative, name)
            for claim in claims:
                result += "<article><p>" + _e(claim.text) + "</p>"
                result += "".join(_observation(bundle, i) for i in claim.observation_indexes)
                result += "</article>"
        elif isinstance(narrative, AiHistoryNarrative) and record.evidence_context is not None:
            claims = getattr(narrative, name)
            for claim in claims:
                result += "<article><p>" + _e(claim.text) + "</p>"
                for index in claim.evidence_indexes:
                    item = record.evidence_context.evidence[index]
                    if isinstance(item, AiHistoryFact):
                        result += _fact(item)
                    else:
                        previous = record.evidence_context.evidence[item.previous_index]
                        current = record.evidence_context.evidence[item.current_index]
                        if not isinstance(previous, AiHistoryFact) or not isinstance(
                            current, AiHistoryFact
                        ):
                            raise ValueError("Invalid comparison facts")
                        result += "<p>Porównanie okresów: " + _metric(item.metric) + "</p>"
                        result += _fact(previous) + _fact(current)
                        result += (
                            "<p>Zmiana wartości: "
                            + _e(
                                item.delta_value
                                if item.delta_value is not None
                                else "Nie wyliczono"
                            )
                            + " "
                            + _e(current.currency or current.unit)
                            + ". Zmiana r/r: "
                            + (
                                _e(item.delta_percent) + "%"
                                if item.delta_percent is not None
                                else "Nie wyliczono"
                            )
                            + ".</p>"
                        )
                        if item.comparison_reason:
                            result += (
                                "<p>Powód ograniczenia: " + _e(item.comparison_reason) + "</p>"
                            )
                result += "</article>"
        else:
            raise ValueError("Completed narrative required")
        if not claims:
            result += "<p>Brak wniosków w tej sekcji na podstawie dostępnych danych.</p>"
    if narrative is None:
        raise ValueError("Completed narrative required")
    result += "<h3>Ograniczenia AI</h3>" + _list(narrative.limitations)
    if record.evidence_context:
        result += (
            "<p>Dowody tej analizy pozostają zamrożone. SHA-256 kontekstu: <code>"
            + _e(record.evidence_context.context_sha256)
            + "</code></p>"
            + _list(record.evidence_context.limitations)
        )
    return result


def render_research_export_html(bundle: "ResearchExport") -> str:
    """Revalidate before rendering; no network, scripts, provider or mutable state."""
    from alphasense.research_export import ResearchExport

    checked = ResearchExport.model_validate(bundle.model_dump(mode="python"))
    report, ratios = checked.report, checked.financial_ratios
    body = (
        "<h1>Raport badawczy</h1><p>Wyłącznie research. Bez składania zleceń "
        "i spersonalizowanych porad inwestycyjnych. Dokument nie zawiera prognozy kursu.</p>"
        "<p>Instrument: "
        + _e(report.input.instrument_id)
        + "<br>Raport: "
        + _e(report.report_id)
        + " · rewizja "
        + _e(report.revision)
        + "<br>Status: "
        + _e(report.status)
        + "<br>Stan danych na: "
        + _e(report.input.as_of.isoformat())
        + "<br>Pochodzenie danych: "
        + _e(report.input.data_origin)
        + "<br>SHA-256 raportu: <code>"
        + _e(report.checksum)
        + "</code></p>"
        + _ai(checked)
    )
    body += "<h2>Dane finansowe raportu</h2><table><thead><tr><th>Metryka</th>"
    body += "<th>Okres</th><th>Wartość / brak</th><th>Dostępność i źródło</th></tr></thead><tbody>"
    for observation in report.input.observations:
        body += (
            "<tr><th>"
            + _metric(observation.metric)
            + "</th><td>"
            + _e(observation.period_start.isoformat())
            + " – "
            + _e(observation.period_end.isoformat())
            + "</td><td>"
        )
        if isinstance(observation, AvailableObservation):
            body += (
                _e(observation.value)
                + " "
                + _e(observation.currency or observation.unit)
                + "</td><td>"
                + _e(observation.available_at.isoformat())
                + "<br>Źródło: "
                + _e(observation.source_id)
                + "<br>Snapshot: "
                + _e(observation.snapshot_id)
            )
        else:
            body += (
                "Nie wyliczono — "
                + _e(observation.status)
                + ": "
                + _e(observation.reason)
                + "</td><td>Brak dostępnej obserwacji"
            )
        body += "</td></tr>"
    body += "</tbody></table>"
    if {"cash_and_equivalents", "long_term_debt_current", "long_term_debt_noncurrent"} <= {
        item.metric for item in report.input.observations if isinstance(item, AvailableObservation)
    }:
        body += (
            "<p>Gotówka i dwie wykazane części długu długoterminowego nie obejmują "
            "wszystkich zobowiązań finansowych. To porównanie nie jest oceną płynności "
            "ani wypłacalności.</p>"
        )
    body += (
        "<h2>Wyniki na przestrzeni lat</h2><p>Dane porównawcze mogą zawierać "
        "przekształcenia; nie odtwarzają wiedzy inwestora w dawnym roku.</p>"
    )
    for series in ratios.history.series:
        body += "<h3>" + _metric(series.metric) + "</h3>"
        if not series.points:
            body += "<p>Nie wyliczono historii. Powód: " + _e(series.reason) + "</p>"
        body += (
            "<table><thead><tr><th>Okres</th><th>Wartość "
            + _e(series.currency)
            + "</th><th>Zmiana wartości</th><th>Zmiana r/r</th><th>Ograniczenie</th>"
            "<th>Data złożenia</th></tr></thead><tbody>"
        )
        for point in series.points:
            body += (
                "<tr><th>"
                + _e(point.period_start)
                + " – "
                + _e(point.period_end)
                + "</th><td>"
                + _e(point.value)
                + "</td><td>"
                + _e(point.delta_value if point.delta_value is not None else "Nie wyliczono")
                + "</td><td>"
                + (
                    _e(point.delta_percent) + "%"
                    if point.delta_percent is not None
                    else "Nie wyliczono"
                )
                + "</td><td>"
                + _e(point.comparison_reason or "—")
                + "</td><td>"
                + _e(point.filing_date)
                + "</td></tr>"
            )
        body += (
            "</tbody></table><p>Sprawozdanie: "
            + _e(series.filing_accession or "Nieustalone")
            + "<br>Dostępne od "
            + _e(series.available_at.isoformat())
            + "<br>Snapshot: "
            + _e(series.source_snapshot_id)
            + "<br>SHA-256: <code>"
            + _e(series.source_sha256)
            + "</code><br>"
            + _link(series.source_url)
            + "</p>"
        )
    body += "<h2>Rentowność i przepływy</h2><table><thead><tr><th>Okres</th>"
    body += "<th>Wskaźnik</th><th>Wartość</th><th>Podstawa</th></tr></thead><tbody>"
    for ratio in ratios.ratios:
        body += (
            "<tr><th>"
            + _e(ratio.period_start)
            + " – "
            + _e(ratio.period_end)
            + "</th><td>"
            + _metric(ratio.metric)
            + "</td><td>"
            + (
                _e(ratio.value_percent) + "%"
                if ratio.value_percent is not None
                else "Nie wyliczono: " + _e(ratio.reason)
            )
            + "</td><td>"
        )
        for operand in ratio.operands:
            body += (
                "<p>"
                + _metric(operand.metric)
                + ": "
                + _e(operand.value)
                + " USD<br>Snapshot: "
                + _e(operand.source_snapshot_id)
                + "<br>SHA-256: <code>"
                + _e(operand.source_sha256)
                + "</code></p>"
            )
        if ratio.available_at:
            body += (
                "<p>Wszystkie składniki dostępne od " + _e(ratio.available_at.isoformat()) + "</p>"
            )
        body += "</td></tr>"
    body += "</tbody></table>" + _list(ratios.limitations)
    body += "<h2>Źródła raportu</h2>" + "".join(_source(source) for source in report.sources)
    body += "<h2>Ograniczenia eksportu</h2>" + _list(checked.limitations)
    body += (
        "<p>Dokument można czytać offline. Otwarcie linków SEC wymaga sieci. "
        "Eksport nie generuje nowej analizy AI.</p><p>Wersja eksportu: "
        + _e(checked.export_version)
        + "<br>SHA-256 eksportu: <code>"
        + _e(checked.checksum)
        + "</code>. Suma kontrolna nie jest podpisem autentyczności.</p>"
    )
    return (
        '<!doctype html><html lang="pl"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="' + _e(HTML_CSP) + '">'
        '<meta name="referrer" content="no-referrer"><title>Raport badawczy</title>'
        "<style>body{font:16px/1.5 system-ui,sans-serif;max-width:1050px;margin:2rem auto;"
        "padding:0 1rem;color:#173c35}table{border-collapse:collapse;width:100%;"
        "display:block;overflow:auto}th,td{border:1px solid #b8c9c0;padding:.5rem;"
        "text-align:left;vertical-align:top}code,p{overflow-wrap:anywhere}article{"
        "border-left:3px solid #b8c9c0;padding-left:1rem;margin:1rem 0}"
        "@media print{body{max-width:none;margin:0}table{display:table;font-size:10pt}"
        "article,tr{break-inside:avoid}}</style></head><body>" + body + "</body></html>"
    )

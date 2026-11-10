"""Standalone, script-free report export. Existing artifacts are never overwritten."""

from html import escape
from pathlib import Path

from alphasense.contracts import AvailableObservation
from alphasense.instrument_contracts import InstrumentRecord
from alphasense.report_contracts import ReportRevision


def report_html(report: ReportRevision, instrument: InstrumentRecord | None = None) -> str:
    checked = ReportRevision.model_validate(report.model_dump(mode="python"))
    label = checked.input.instrument_id
    if instrument is not None:
        identity = InstrumentRecord.model_validate(instrument.model_dump(mode="python"))
        if (
            str(identity.instrument_id) != checked.input.instrument_id
            or identity.asset_type != checked.input.asset_type
            or identity.data_origin != checked.input.data_origin
        ):
            raise ValueError("Report export instrument identity conflict")
        label = f"{identity.symbol} — {identity.display_name}"
    rows = []
    for item in checked.input.observations:
        value = repr(item.value) if isinstance(item, AvailableObservation) else "brak"
        available = (
            item.available_at.isoformat() if isinstance(item, AvailableObservation) else "brak"
        )
        cells = (
            item.metric,
            item.status,
            value,
            item.unit,
            item.currency or "—",
            item.period_start.isoformat(),
            item.period_end.isoformat(),
            available,
        )
        rows.append("<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in cells) + "</tr>")
    sections = []
    for title, section in (
        ("Fundamenty", checked.fundamental_section),
        ("Technika", checked.technical_section),
        ("Synteza", checked.synthesis_section),
        ("Scenariusze", checked.scenario_section),
    ):
        findings = "".join(f"<li>{escape(finding.text)}</li>" for finding in section.findings)
        sections.append(
            f"<section><h2>{title}: {escape(section.status)}</h2>"
            f"<p>{escape(section.reason or '')}</p><ul>{findings}</ul></section>"
        )
    sources = []
    for source in checked.sources:
        source_label = escape(f"{source.source_id} / {source.snapshot_id}")
        link = (
            (
                f'<a href="{escape(str(source.url), quote=True)}" rel="noreferrer noopener">'
                f"{source_label}</a>"
            )
            if source.url is not None
            else source_label
        )
        sources.append(
            f"<li>{link}<br>SHA256: <code>{source.sha256}</code><br>"
            f"Pobrano: {escape(source.retrieved_at.isoformat())}<br>"
            f"Warunki: {escape(source.license)}</li>"
        )
    limitations = "".join(f"<li>{escape(item)}</li>" for item in checked.limitations)
    uncertainties = "".join(f"<li>{escape(item)}</li>" for item in checked.uncertainties)
    return (
        '<!doctype html><html lang="pl"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">"
        "<title>Raport badawczy</title><style>body{font:16px system-ui;max-width:1200px;"
        "margin:2rem auto;padding:0 1rem;color:#17212b}table{border-collapse:collapse;"
        "font-size:.85rem}td,th{border:1px solid #bbc4cc;padding:.45rem;text-align:left}"
        ".table{overflow:auto}code{overflow-wrap:anywhere}li{margin:.6rem 0}</style>"
        f"<main><h1>{escape(label)}</h1><p>Raport badawczy: {escape(checked.status)}</p>"
        f"<p>Instrument: {escape(checked.input.instrument_id)}<br>"
        f"Dane as of: {escape(checked.input.as_of.isoformat())}<br>"
        f"Pochodzenie: {escape(checked.input.data_origin)}<br>"
        f"Metoda: {escape(checked.methodology_version)}</p>"
        f"<p>{escape(checked.disclaimer)}</p>"
        '<h2>Obserwacje</h2><div class="table"><table><thead><tr>'
        "<th>Metryka</th><th>Status</th><th>Wartość</th><th>Jednostka</th><th>Waluta</th>"
        "<th>Początek okresu</th><th>Koniec okresu</th><th>Dostępne od</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
        + "".join(sections)
        + "<h2>Źródła</h2><ul>"
        + "".join(sources)
        + "</ul>"
        + f"<h2>Niepewności</h2><ul>{uncertainties}</ul>"
        + f"<h2>Ograniczenia</h2><ul>{limitations}</ul>"
        + f"<p>Rewizja: {checked.revision_id}<br>Checksum: <code>{checked.checksum}</code></p>"
        + "</main></html>\n"
    )


def export_report(
    report: ReportRevision, directory: Path, instrument: InstrumentRecord | None = None
) -> tuple[Path, Path]:
    checked = ReportRevision.model_validate(report.model_dump(mode="python"))
    target = directory / str(checked.revision_id)
    if target.is_symlink():
        raise ValueError("Report export directory must not be a symbolic link")
    target.mkdir(parents=True, exist_ok=True)
    json_path, html_path = target / "report.json", target / "report.html"
    content = (
        (json_path, (checked.model_dump_json(indent=2) + "\n").encode("utf-8")),
        (html_path, report_html(checked, instrument).encode("utf-8")),
    )
    for path, raw in content:
        if path.is_symlink():
            raise ValueError("Report export file must not be a symbolic link")
        try:
            with path.open("xb") as stream:
                stream.write(raw)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise ValueError("Existing report export differs; refusing to overwrite") from None
    return json_path, html_path

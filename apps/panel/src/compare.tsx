import {useEffect, useId, useState} from 'react';
import type {components} from './schema';
import {compareReports} from './report-compare';
import {metricLabels, observationPeriod} from './report-display';

type Models = components['schemas'];
type Report = Models['ReportRevision'];
type Observation = Report['input']['observations'][number];
type Selection = {reportId: string; revision: number};
type Props = {instrumentId: string; currentReportId: string; currentRevision: number};
const number = (value: number) => new Intl.NumberFormat('pl-PL', {maximumSignificantDigits: 15}).format(value);
const timestamp = (value: string) => new Intl.DateTimeFormat('pl-PL', {dateStyle:'medium', timeStyle:'short', timeZone:'UTC'}).format(new Date(value)) + ' UTC';
const identity = (selection: Selection) => selection.reportId + '/' + selection.revision;
async function read<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, {signal, cache:'no-store', headers:{Accept:'application/json'}});
  if (!response.ok) throw Error(response.status === 503 ? 'Baza danych jest niedostępna.' : 'Nie udało się odczytać zapisanych analiz (' + response.status + ').');
  return await response.json() as T;
}
function Value({observation}: {observation: Observation | null}) {
  if (!observation) return <span>Brak jednoznacznej obserwacji</span>;
  if (observation.status !== 'available') return <><b>{observation.status === 'missing' ? 'Brak danych' : 'Nie dotyczy'}</b><small>{observation.reason}</small></>;
  return <><b>{number(observation.value)}</b><small>Źródło: {observation.source_id}</small><small>Snapshot: {observation.snapshot_id}</small><small>Dostępne od {timestamp(observation.available_at)}</small></>;
}
export function ReportComparison(props: Props) {
  return <Comparison key={props.instrumentId + '/' + props.currentReportId + '/' + props.currentRevision} {...props}/>;
}
function Comparison({instrumentId, currentReportId, currentRevision}: Props) {
  const inputId = useId();
  const [pages, setPages] = useState<string[]>(['']);
  const [page, setPage] = useState<Models['PanelRunPage']>();
  const [pageError, setPageError] = useState('');
  const [retry, setRetry] = useState(0);
  const [selection, setSelection] = useState<Selection>();
  const [reports, setReports] = useState<{key: string; left: Report; right: Report}>();
  const [reportError, setReportError] = useState('');
  const after = pages[pages.length - 1];
  const selectionKey = selection ? identity(selection) : '';
  useEffect(() => {
    const abort = new AbortController();
    setPage(undefined); setPageError('');
    const query = new URLSearchParams({instrument_id:instrumentId, limit:'50'});
    if (after) query.set('after_id', after);
    read<Models['PanelRunPage']>('/v1/panel/runs?' + query, abort.signal)
      .then(value => {if (!abort.signal.aborted) setPage(value);})
      .catch(error => {if (!abort.signal.aborted) setPageError(error instanceof TypeError ? 'Brak połączenia z lokalnym panelem.' : String(error.message));});
    return () => abort.abort();
  }, [instrumentId, after, retry]);
  useEffect(() => {
    setReportError(''); setReports(undefined);
    if (!selection) return;
    const abort = new AbortController();
    const reportUrl = (id: string, revision: number) => '/v1/reports/' + encodeURIComponent(id) + '/revisions/' + revision;
    Promise.all([
      read<Report>(reportUrl(currentReportId, currentRevision), abort.signal),
      read<Report>(reportUrl(selection.reportId, selection.revision), abort.signal),
    ]).then(([left, right]) => {if (!abort.signal.aborted) setReports({key:selectionKey, left, right});})
      .catch(error => {if (!abort.signal.aborted) setReportError(error instanceof TypeError ? 'Brak połączenia z lokalnym panelem.' : String(error.message));});
    return () => abort.abort();
  }, [selectionKey, currentReportId, currentRevision, retry]);
  const choices = (page?.items ?? []).filter(run => run.report_id && run.revision)
    .filter((run, index, values) => values.findIndex(other => other.report_id === run.report_id && other.revision === run.revision) === index)
    .filter(run => run.report_id !== currentReportId || run.revision !== currentRevision);
  let comparison: ReturnType<typeof compareReports> | undefined;
  let comparisonError = '';
  if (reports?.key === selectionKey) {
    try {comparison = compareReports(reports.left, reports.right);} catch (error) {comparisonError = (error as Error).message;}
  }
  return <section className="comparison" aria-labelledby={inputId + '-title'}>
    <h3 id={inputId + '-title'}>Porównaj zapisane analizy</h3>
    <p>Raport A to otwarta analiza, rewizja {currentRevision}. Wybierz raport B tej samej spółki. Różnica oznacza B − A; liczymy ją wyłącznie dla zgodnej metryki, jednostki, waluty i okresu.</p>
    <label htmlFor={inputId}>Raport B</label>
    <select id={inputId} value={selectionKey} disabled={!page} onChange={event => {
      const run = choices.find(item => item.report_id + '/' + item.revision === event.target.value);
      setSelection(run?.report_id && run.revision ? {reportId:run.report_id, revision:run.revision} : undefined);
    }}>
      <option value="">Wybierz analizę do porównania</option>
      {selection && !choices.some(run => run.report_id + '/' + run.revision === selectionKey) && <option value={selectionKey}>Wybrany raport {selection.reportId.slice(0, 8)} · rewizja {selection.revision}</option>}
      {choices.map(run => <option key={run.report_id + '/' + run.revision} value={run.report_id + '/' + run.revision}>{timestamp(run.created_at)} · {run.report_id!.slice(0,8)} · rewizja {run.revision}</option>)}
    </select>
    {pageError && <p role="alert">{pageError}</p>}
    {!page && !pageError && <p role="status">Wczytywanie zapisanych analiz…</p>}
    {page && choices.length === 0 && <p>Na tej stronie nie ma innego raportu do porównania.</p>}
    {(pages.length > 1 || page?.next_after_id) && <nav aria-label="Strony analiz do porównania">
      <button disabled={pages.length <= 1 || !page} onClick={() => setPages(previous => previous.slice(0,-1))}>← Wstecz</button>
      <button disabled={!page?.next_after_id} onClick={() => {if (page?.next_after_id) setPages(previous => [...previous, page.next_after_id!]);}}>Dalej →</button>
    </nav>}
    {(reportError || comparisonError) && <p role="alert">{reportError || comparisonError}</p>}
    {(pageError || reportError) && <button onClick={() => setRetry(previous => previous + 1)}>Spróbuj ponownie</button>}
    {selection && !reports && !reportError && <p role="status">Wczytywanie dwóch dokładnych rewizji…</p>}
    {comparison && reports && <>
      <div className="comparison-meta"><p><b>Raport A</b><br/>{reports.left.report_id} · rewizja {reports.left.revision}<br/>Utworzono {timestamp(reports.left.generated_at_utc)}<br/>Stan danych na {timestamp(reports.left.input.as_of)}</p><p><b>Raport B</b><br/>{reports.right.report_id} · rewizja {reports.right.revision}<br/>Utworzono {timestamp(reports.right.generated_at_utc)}<br/>Stan danych na {timestamp(reports.right.input.as_of)}</p></div>
      {comparison.warnings.map((warning, index) => <p className="hint" key={index}>{warning}</p>)}
      <p className="hint">Odmienne okresy pokazujemy osobno. To porównanie zapisanych obserwacji, bez obliczania wzrostu rok do roku.</p>
      <div className="comparison-table" tabIndex={0} aria-label="Przewijana tabela porównania"><table>
        <thead><tr><th scope="col">Metryka i okres</th><th scope="col">Raport A</th><th scope="col">Raport B</th><th scope="col">Różnica B − A</th></tr></thead>
        <tbody>{comparison.rows.map(row => <tr key={row.key}>
          <th scope="row">{metricLabels[row.metric] ?? row.metric}<small>{observationPeriod(row.period_start, row.period_end)}</small><small>{row.currency ?? row.unit} · {row.unit}</small></th>
          <td><Value observation={row.left}/></td><td><Value observation={row.right}/></td>
          <td>{row.delta === null ? 'Nieporównywalne' : number(row.delta)}{row.percent !== null && <small>{number(row.percent)}%</small>}{row.reason && <small>{row.reason}</small>}</td>
        </tr>)}</tbody>
      </table></div>
      {comparison.rows.length === 0 && <p>Raporty nie zawierają obserwacji do porównania.</p>}
    </>}
  </section>;
}

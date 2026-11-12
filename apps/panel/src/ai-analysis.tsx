import {useEffect, useRef, useState} from 'react';
import type {components} from './schema';
import {metricLabels, observationPeriod} from './report-display';
import {assertAiBudget, verifyAiRecord, verifyAiRecordList, canGenerateAi, parseAiAttempt, selectAiAttempt} from './ai-analysis-state';
import type {AiAnalysisRecord, AiAttempt, AiBudget, AiClaim} from './ai-analysis-state';
import type {AiHistoryClaim,AiHistoryContext,AiHistoryFact,AiHistoryNarrative} from './ai-history-context';
import {formatHistoryDecimal,comparisonExplanation} from './financial-history-state';

type Report = components['schemas']['ReportRevision'];
const date = (value: string) => new Intl.DateTimeFormat('pl-PL', {dateStyle:'medium', timeStyle:'short', timeZone:'Europe/Warsaw'}).format(new Date(value));
const price = (value: string) => value.replace('.', ',') + ' zł';

function readAttempt(key: string, report: Report): AiAttempt | undefined {
  try { return parseAiAttempt(sessionStorage.getItem(key), report); } catch { return undefined; }
}
function remember(key: string, attempt: AiAttempt | undefined) {
  try {
    if (attempt) sessionStorage.setItem(key, JSON.stringify(attempt));
    else sessionStorage.removeItem(key);
  } catch { /* The mounted view still retains the same request identity. */ }
}
async function jsonResponse(response: Response): Promise<unknown> {
  if (!response.ok) {
    let message = response.status === 404 ? 'Nie znaleziono zapisanego zlecenia.' : 'Nie udało się odczytać analizy AI (' + response.status + ').';
    try {
      const data = await response.json();
      if (typeof data?.detail?.message === 'string') message = data.detail.message;
    } catch { /* Keep the local message for non-JSON errors. */ }
    throw Error(message);
  }
  return response.json();
}

export function AiAnalysis({report}: {report: Report}) {
  const key = 'alphasense-ai-attempt:' + report.report_id + ':' + report.revision + ':' + report.checksum;
  const available = new Set(report.input.observations.flatMap((observation, index) => observation.status === 'available' ? [index] : []));
  const [attempt, setAttempt] = useState<AiAttempt | undefined>(() => readAttempt(key, report));
  const [records, setRecords] = useState<AiAnalysisRecord[]>([]);
  const [selected, setSelected] = useState('');
  const [budget, setBudget] = useState<AiBudget>();
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const controller = useRef<AbortController | undefined>(undefined);
  const busy = useRef(false);
  const mounted = useRef(false);
  const active = records.find(item => item.request_id === selected) ?? records[0];

  function accept(record: AiAnalysisRecord) {
    setRecords(previous => [record, ...previous.filter(item => item.request_id !== record.request_id)].slice(0, 20));
    setSelected(record.request_id);
    if (record.status !== 'running') { setAttempt(undefined); remember(key, undefined); }
  }

  useEffect(() => {
    mounted.current = true;
    const abort = new AbortController();
    const timer = setTimeout(() => {
      if (mounted.current && !abort.signal.aborted) {
        setError('Odczyt zapisanych analiz trwa zbyt długo. Odśwież wyniki; model nie jest uruchamiany przy odczycie.');
        setLoading(false);
        abort.abort();
      }
    }, 15000);
    const params = new URLSearchParams({report_id:report.report_id, revision:String(report.revision)});
    setLoading(true); setError('');
    const options = {cache:'no-store' as const, signal:abort.signal, headers:{Accept:'application/json'}};
    Promise.allSettled([
      fetch('/v1/panel/ai-analyses?' + params, options).then(jsonResponse).then(async value => {
        const verified = await verifyAiRecordList(value, report, available);
        if (!abort.signal.aborted) {
          setRecords(verified);
          const saved = readAttempt(key, report);
          const result = saved && verified.find(item => item.request_id === saved.request_id);
          if (result && result.status !== 'running') { setAttempt(undefined); remember(key, undefined); }
        }
      }),
      fetch('/v1/panel/ai-budget', options).then(jsonResponse).then(value => {
        assertAiBudget(value);
        if (!abort.signal.aborted) setBudget(value);
      }),
    ]).then(results => {
      clearTimeout(timer);
      if (!abort.signal.aborted) {
        const failure = results.find(result => result.status === 'rejected');
        if (failure?.status === 'rejected') setError(failure.reason instanceof Error ? failure.reason.message : 'Nie udało się odczytać danych AI.');
        setLoading(false);
      }
    });
    return () => {mounted.current = false; clearTimeout(timer); abort.abort(); controller.current?.abort();};
  }, [key, retry]);

  async function perform(mode: 'generate' | 'recover') {
    if (busy.current || loading || (mode === 'generate' && !attempt && !canGenerateAi(budget))) return;
    busy.current = true; setPending(true); setError('');
    const abort = new AbortController(); controller.current = abort;
    const timer = setTimeout(() => abort.abort(), 45000);
    let current: AiAttempt | undefined;
    try {
      current = mode === 'recover' ? attempt : selectAiAttempt(report, attempt, () => crypto.randomUUID());
      if (!current) throw Error('Brak zlecenia do sprawdzenia.');
      setAttempt(current); remember(key, current);
      const response = await fetch(mode === 'recover' ? '/v1/panel/ai-analyses/' + encodeURIComponent(current.request_id) : '/v1/panel/ai-analyses', {
        method: mode === 'recover' ? 'GET' : 'POST', signal:abort.signal, cache:'no-store',
        headers: mode === 'recover' ? {Accept:'application/json'} : {'Content-Type':'application/json', 'X-AlphaSense-Panel':'1', Accept:'application/json'},
        ...(mode === 'generate' ? {body:JSON.stringify({request_id:current.request_id, report_id:current.report_id, revision:current.revision})} : {}),
      });
      const value = await verifyAiRecord(await jsonResponse(response), report, available, current.request_id);
      if (mounted.current && !abort.signal.aborted) accept(value);
      // This read cannot initiate or repeat a model call.
      const nextBudget = await fetch('/v1/panel/ai-budget', {signal:abort.signal, cache:'no-store', headers:{Accept:'application/json'}}).then(jsonResponse);
      assertAiBudget(nextBudget);
      if (mounted.current && !abort.signal.aborted) setBudget(nextBudget);
    } catch (failure) {
      if (mounted.current) setError(abort.signal.aborted ? 'Oczekiwanie przerwano. Zlecenie mogło zostać zapisane — sprawdź je przed następną próbą.' : failure instanceof TypeError ? 'Brak połączenia. Zachowano to samo zlecenie; sprawdź jego wynik.' : failure instanceof Error ? failure.message : 'Nie udało się uzyskać analizy AI.');
    } finally {
      clearTimeout(timer); busy.current = false;
      if (mounted.current) setPending(false);
    }
  }

  const running = records.some(item => item.status === 'running');
  const cashDebtComparison = ['cash_and_equivalents', 'long_term_debt_current', 'long_term_debt_noncurrent'].every(metric => report.input.observations.some(observation => observation.status === 'available' && observation.metric === metric));
  return <section aria-labelledby="ai-analysis-title">
    <p className="eyebrow">INTERPRETACJA DANYCH</p><h2 id="ai-analysis-title">Analiza AI</h2>
    <p>Podsumowanie po polsku, mocne strony i ryzyka na podstawie danych raportu i przypisanych okresów porównawczych. AI może błędnie zinterpretować dane — przy każdym wniosku możesz sprawdzić podstawę.</p>
    {budget && <p>Na analizy AI pozostało <strong>{price(budget.remaining_pln)}</strong>. Nowa próba rezerwuje {price(budget.reservation_per_attempt_pln)}; otwarcie zapisanej analizy nie wywołuje modelu.</p>}
    {budget && !budget.enabled && <p>Generowanie jest wyłączone. {budget.reason}</p>}
    {loading && <p role="status">Wczytywanie zapisanych analiz…</p>}
    {error && <p role="alert">{error}</p>}
    {!pending && <div className="actions">
      <button disabled={loading} onClick={() => setRetry(value => value + 1)}>Odśwież zapisane wyniki</button>
      {attempt ? <>
        <button disabled={loading} onClick={() => void perform('recover')}>Sprawdź zapisane zlecenie</button>
        <button disabled={loading} onClick={() => void perform('generate')}>Ponów to samo żądanie</button>
      </> : <button disabled={loading || !canGenerateAi(budget) || running || report.input.data_origin !== 'live'} onClick={() => void perform('generate')}>{records.some(item => item.status === 'completed') ? 'Wygeneruj nową analizę AI' : 'Generuj analizę AI'}</button>}
    </div>}
    {pending && <p role="status">Oczekiwanie na wynik. Nie uruchamiaj kolejnej analizy.</p>}
    {attempt && <p>Zachowano identyfikator tej próby. Ponowienie tego samego żądania nie zleca kolejnej generacji. Sprawdzenie i otwarcie zapisanej analizy nie wywołują modelu.</p>}
    {!attempt && running && <p>Istnieje rozpoczęte zlecenie. Odśwież zapisane wyniki; nie uruchamiamy drugiego automatycznie.</p>}
    {budget && <details><summary>Szczegóły limitu AI</summary><p>Łączny limit {price(budget.budget_pln)}, bez automatycznego odnawiania. Zarezerwowano {price(budget.reserved_pln)}. Każda nowa próba rezerwuje {price(budget.reservation_per_attempt_pln)}, także po błędzie. To aplikacyjny limit rezerwacji; nie obejmuje użycia klucza poza aplikacją.</p>{!canGenerateAi(budget) && budget.enabled && <p>Limit nie pozwala na następną próbę. Zapisane wyniki są nadal dostępne.</p>}</details>}
    {report.input.data_origin !== 'live' && <p>Ten raport zawiera dane syntetyczne. Generowanie z panelu jest dostępne dla rzeczywistych raportów.</p>}
    {!loading && !active && <p>Nie ma jeszcze zapisanej analizy AI dla tej rewizji. Po wygenerowaniu wynik pozostanie w archiwum.</p>}
    {records.length > 1 && <><label htmlFor="ai-analysis-history">Zapisane analizy AI</label><select id="ai-analysis-history" value={active?.request_id ?? ''} onChange={event => setSelected(event.target.value)}>{records.map(record => <option key={record.request_id} value={record.request_id}>{date(record.created_at)} · {record.status === 'completed' ? 'Gotowa' : record.status === 'failed' ? 'Błąd' : 'W toku'}</option>)}</select></>}
    {active?.status === 'running' && <p role="status">Zlecenie jest zapisane jako rozpoczęte. Odśwież wynik. Po przerwaniu procesu nie jest ponawiane automatycznie.</p>}
    {active?.status === 'failed' && <p role="alert">Nie udało się wygenerować poprawnej analizy. Kod: {active.error_code}. Ta próba pozostaje w historii i zużyła rezerwację.</p>}
    {active?.status === 'completed' && active.analysis && <>
      <p><strong>{active.prompt_version==='report-history-v2'?'Analiza z historią':'Analiza wcześniejsza — bez historii'}</strong> · zapisana {date(active.finished_at!)} · dane na {date(report.input.as_of)}</p>
      <div className="actions"><a download href={'/v1/panel/reports/'+encodeURIComponent(report.report_id)+'/'+report.revision+'/research-export/html?ai_request_id='+encodeURIComponent(active.request_id)}>Pobierz pełną analizę HTML</a><a download href={'/v1/panel/reports/'+encodeURIComponent(report.report_id)+'/'+report.revision+'/research-export?ai_request_id='+encodeURIComponent(active.request_id)}>Pobierz pełną analizę JSON</a></div>
      <p>Eksport zawiera tę wybraną analizę AI, dane porównawcze, wskaźniki i źródła. Nie uruchamia modelu.</p>
      {active.evidence_context?.evidence.some(item=>item.kind==='comparison'&&item.comparison_reason==='PERIODS_NOT_COMPARABLE')&&<p role="note">Nie wszystkie okresy są porównywalne. Wnioski o zmianach dotyczą wyłącznie wskazanych par okresów; nie opisują trendu przez lukę w danych.</p>}
      <VersionedClaims title="Najważniejsze wnioski" record={active} section="summary" report={report}/>
      <VersionedClaims title="Mocne strony" record={active} section="strengths" report={report}/>
      <VersionedClaims title="Ryzyka" record={active} section="risks" report={report}/>
      {cashDebtComparison && <p role="note">Analiza porównuje gotówkę z dwiema wykazanymi częściami długu długoterminowego. Dane nie obejmują wszystkich zobowiązań finansowych. To porównanie nie jest oceną płynności ani wypłacalności.</p>}
      <VersionedClaims title="Co warto sprawdzić" record={active} section="questions" report={report}/>
      <h3>Ograniczenia analizy</h3><ul>{active.analysis.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul>
      <details><summary>Pochodzenie analizy AI</summary><p>Model: {active.model_id}. Wersja instrukcji: {active.prompt_version}. Raport: rewizja {active.revision}. Zapisane wyniki są odczytywane bez kolejnej generacji.</p>{active.evidence_context&&<><p>Dowody pozostają przypisane do tej analizy. Odświeżenie tabeli historii nie zmienia zapisanych cytowań.</p><p>SHA-256 kontekstu: <code>{active.evidence_context.context_sha256}</code></p><ul>{active.evidence_context.limitations.map((item,index)=><li key={index}>{item}</li>)}</ul></>}</details>
    </>}
  </section>;
}

function VersionedClaims({title,record,section,report}:{title:string;record:AiAnalysisRecord;section:'summary'|'strengths'|'risks'|'questions';report:Report}) {
  if(record.prompt_version==='report-history-v2'&&record.evidence_context) return <HistoryClaims title={title} claims={(record.analysis as AiHistoryNarrative)[section]} context={record.evidence_context}/>;
  return <Claims title={title} claims={(record.analysis as import('./ai-analysis-state').AiNarrative)[section]} report={report}/>;
}

function HistoryFact({fact}:{fact:AiHistoryFact}) {
  return <p><strong>{metricLabels[fact.metric]??fact.metric}: {formatHistoryDecimal(fact.value)} {fact.currency??fact.unit}</strong><br/>{observationPeriod(fact.period_start,fact.period_end)}<br/>Dostępne od {date(fact.available_at)} · {fact.source.source_id}{fact.source.url&&<> · <a href={fact.source.url} target="_blank" rel="noreferrer">Źródło ↗</a></>}</p>;
}

function HistoryClaims({title,claims,context}:{title:string;claims:AiHistoryClaim[];context:AiHistoryContext}) {
  if(claims.length===0) return <><h3>{title}</h3><p>Brak wniosków w tej sekcji na podstawie dostępnych danych.</p></>;
  return <><h3>{title}</h3>{claims.map((claim,index)=><div className="source" key={index}><p>{claim.text}</p>{claim.kind==='trend'&&claim.evidence_indexes.map(position=>{
    const item=context.evidence[position];
    if(item.kind!=='comparison') return null;
    const previous=context.evidence[item.previous_index] as AiHistoryFact,current=context.evidence[item.current_index] as AiHistoryFact;
    return <p key={position}><strong>{metricLabels[item.metric]??item.metric}: {formatHistoryDecimal(previous.value)} → {formatHistoryDecimal(current.value)} {current.currency??current.unit}</strong><br/>{observationPeriod(previous.period_start,previous.period_end)} → {observationPeriod(current.period_start,current.period_end)}<br/>Zmiana: {item.delta_value===null?'Nie wyliczono':formatHistoryDecimal(item.delta_value)+' '+(current.currency??current.unit)}{item.delta_percent!==null&&<> ({formatHistoryDecimal(item.delta_percent)}%)</>}{item.comparison_reason&&<> · {comparisonExplanation(item.comparison_reason)}</>}</p>;
  })}<details><summary>Sprawdź przypisane dane ({claim.evidence_indexes.length})</summary>{claim.evidence_indexes.map(position=>{
    const evidence=context.evidence[position];
    if(evidence.kind==='fact') return <HistoryFact key={position} fact={evidence}/>;
    const previous=context.evidence[evidence.previous_index] as AiHistoryFact,current=context.evidence[evidence.current_index] as AiHistoryFact;
    return <div key={position}><p><strong>{metricLabels[evidence.metric]??evidence.metric} — porównanie okresów</strong></p><HistoryFact fact={previous}/><HistoryFact fact={current}/><p>Zmiana wartości: {evidence.delta_value===null?'Nie wyliczono':formatHistoryDecimal(evidence.delta_value)+' '+(current.currency??current.unit)}. Zmiana r/r: {evidence.delta_percent===null?'Nie wyliczono':formatHistoryDecimal(evidence.delta_percent)+'%'}.</p>{evidence.comparison_reason&&<p>{comparisonExplanation(evidence.comparison_reason)}</p>}</div>;
  })}</details></div>)}</>;
}

function Claims({title, claims, report}: {title: string; claims: AiClaim[]; report: Report}) {
  if (claims.length === 0) return <><h3>{title}</h3><p>Brak wniosków w tej sekcji na podstawie dostępnych danych.</p></>;
  return <><h3>{title}</h3>{claims.map((claim, index) => <div className="source" key={index}><p>{claim.text}</p><details><summary>Sprawdź dane ({claim.observation_indexes.length})</summary>{claim.observation_indexes.map(position => {
    const observation = report.input.observations[position];
    if (observation.status !== 'available') return null;
    const source = report.sources.find(item => item.source_id === observation.source_id && item.snapshot_id === observation.snapshot_id);
    return <p key={position}><strong>{metricLabels[observation.metric] ?? observation.metric}: {new Intl.NumberFormat('pl-PL', {maximumSignificantDigits:15}).format(observation.value)} {observation.currency ?? observation.unit}</strong><br/>{observationPeriod(observation.period_start, observation.period_end)}<br/>Dostępne od {date(observation.available_at)} · {observation.source_id}{source?.url && /^https?:\/\//i.test(source.url) && <> · <a href={source.url} target="_blank" rel="noreferrer">Źródło ↗</a></>}</p>;
  })}</details></div>)}</>;
}

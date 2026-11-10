import {useEffect, useRef, useState} from 'react';
import type {components} from './schema';
import {attemptKey, attemptHistoryKey, attemptIdentity, marketLabel, isSupported, normalizeSymbol, parseAttempt, parseAttempts, selectAttempt} from './launch-state';
import type {Attempt, Market} from './launch-state';
import {assertTaskIdentity, completedAnalysis, shouldPollTask, taskStages} from './task-state';
import type {Task} from './task-state';

type Result = Task;
type CatalogPage = components['schemas']['CatalogPage'];
export type StartedAnalysis = components['schemas']['PanelAnalysisResult'] & {symbol: string};
function savedAttempt(): Attempt | undefined {
  try { return parseAttempt(sessionStorage.getItem(attemptKey)); } catch { return undefined; }
}
function remember(attempt: Attempt | undefined) {
  try {
    if (attempt) sessionStorage.setItem(attemptKey, JSON.stringify(attempt));
    else sessionStorage.removeItem(attemptKey);
  } catch { /* The current tab still retains the retry identity in React state. */ }
}
function savedHistory(): Attempt[] {
  try { return parseAttempts(sessionStorage.getItem(attemptHistoryKey)); } catch { return []; }
}
function rememberHistory(history: Attempt[]) {
  try { sessionStorage.setItem(attemptHistoryKey, JSON.stringify(history)); } catch { /* Keep the in-memory retry identities. */ }
}
async function responseResult(response: Response): Promise<Result> {
  if (!response.ok) {
    let message = response.status === 404 ? 'Zadanie nie zostało jeszcze zapisane. Możesz ponowić to samo żądanie.' : 'Nie udało się uruchomić analizy (' + response.status + ').';
    try {
      const body = await response.json();
      if (typeof body?.detail?.message === 'string') message = body.detail.message;
    } catch { /* A non-JSON error must not hide the retry action. */ }
    throw new Error(message);
  }
  return await response.json() as Result;
}
export function LaunchAnalysis({suggestion, onResult, onTaskChange}: {suggestion: string; onResult: (result: StartedAnalysis) => void; onTaskChange?: () => void}) {
  const [attempt, setAttempt] = useState<Attempt | undefined>(savedAttempt);
  const [history, setHistory] = useState<Attempt[]>(savedHistory);
  const [symbol, setSymbol] = useState(() => savedAttempt()?.symbol ?? 'GOOGL');
  const [market, setMarket] = useState<Market>(() => savedAttempt()?.exchange_mic ?? null);
  const [catalog, setCatalog] = useState<CatalogPage>();
  const [catalogQuery, setCatalogQuery] = useState('');
  const [catalogBusy, setCatalogBusy] = useState(false);
  const [catalogError, setCatalogError] = useState('');
  async function searchCatalog(refresh=false) {
    setCatalogBusy(true); setCatalogError('');
    try {
      const response = await fetch(refresh ? '/v1/panel/catalog/refresh' : '/v1/panel/catalog?query='+encodeURIComponent(catalogQuery), refresh ? {method:'POST',headers:{'Content-Type':'application/json','X-AlphaSense-Panel':'1'},body:'{}'} : {cache:'no-store'});
      if(!response.ok) {let message='Nie udało się odczytać katalogu SEC.'; try {const body=await response.json(); if(typeof body?.detail?.message==='string')message=body.detail.message;}catch{} throw Error(message);}
      setCatalog(await response.json() as CatalogPage);
    } catch(error) {setCatalogError(error instanceof TypeError ? 'Brak połączenia z lokalnym panelem.' : (error as Error).message);} finally {setCatalogBusy(false);}
  }
  const [pending, setPending] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<Result>();
  const [poll, setPoll] = useState(0);
  const busy = useRef(false);
  const callback = useRef(onResult);
  callback.current = onResult;
  const taskCallback = useRef(onTaskChange);
  taskCallback.current = onTaskChange;
  const controller = useRef<AbortController | undefined>(undefined);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => { if (!attempt && isSupported(suggestion)) setSymbol(normalizeSymbol(suggestion)); }, [suggestion, attempt]);
  function accept(value: Result, identity: Attempt) {
    assertTaskIdentity(value, identity);
    setResult(value);
    setError('');
    const finishedReport = completedAnalysis(value);
    if (finishedReport) callback.current(finishedReport);
    taskCallback.current?.();
    if (value.status === 'completed' || value.status === 'failed') {
      remember(undefined);
      setHistory(previous => {const next = previous.filter(item => item.run_id !== identity.run_id); rememberHistory(next); return next;});
    }
  }
  async function check(identity: Attempt) {
    if (busy.current) return;
    busy.current = true; setChecking(true);
    const abort = new AbortController(); controller.current = abort;
    const timer = setTimeout(() => abort.abort(), 30000);
    try { accept(await responseResult(await fetch('/v1/panel/tasks/' + identity.run_id, {signal: abort.signal, cache:'no-store'})), identity); }
    catch (error) { setError(error instanceof TypeError || abort.signal.aborted ? 'Nie można teraz sprawdzić stanu. Żądanie może nadal trwać. Sprawdź ponownie.' : (error as Error).message); }
    finally { clearTimeout(timer); busy.current = false; setChecking(false); }
  }
  useEffect(() => { if(attempt) void check(attempt); }, []);
  useEffect(() => {
    if (!attempt || !shouldPollTask(result, poll, error)) return;
    const timer = setTimeout(() => { setPoll(n => n + 1); void check(attempt); }, 3000);
    return () => clearTimeout(timer);
  }, [attempt, result, poll, error]);
  async function start() {
    if (busy.current) return;
    if (market === 'XWAR') { setError('Adapter GPW jest w przygotowaniu. Zlecenie nie zostanie wysłane do SEC.'); return; }
    if (!isSupported(symbol)) { setError('Wpisz prawidłowy symbol spółki, np. MSFT lub BRK-B.'); return; }
    const identity = selectAttempt(symbol, attempt ?? history.find(item => attemptIdentity(item) === attemptIdentity({symbol:normalizeSymbol(symbol),exchange_mic:market})), () => crypto.randomUUID(), market);
    setAttempt(identity); remember(identity); setError(''); setPending(true); busy.current = true; setPoll(0);
    const abort = new AbortController(); controller.current = abort;
    const timer = setTimeout(() => abort.abort(), 30000);
    try {
      const body: components['schemas']['TaskCreate'] = identity;
      accept(await responseResult(await fetch('/v1/panel/tasks', {
        method:'POST', headers:{'Content-Type':'application/json','X-AlphaSense-Panel':'1'},
        body:JSON.stringify(body), signal:abort.signal,
      })), identity);
    } catch (error) {
      setError(error instanceof TypeError || abort.signal.aborted ? 'Połączenie przerwano. Analiza może nadal trwać. Sprawdź stan lub ponów to samo żądanie — zachowamy jego identyfikator.' : (error as Error).message);
    } finally { clearTimeout(timer); busy.current = false; setPending(false); }
  }
  function parkAttempt() {
    if (!attempt || busy.current) return;
    const next = [attempt, ...history.filter(item => attemptIdentity(item) !== attemptIdentity(attempt))];
    setHistory(next); rememberHistory(next);
    setAttempt(undefined); remember(undefined); setResult(undefined); setError(''); setSymbol('');
  }
  const finished = result?.status === 'completed' || result?.status === 'failed';
  return <section className="launch" aria-labelledby="launch-title">
    <h2 id="launch-title">Nowa analiza</h2>
    <p>Wybierz spółkę z zapisanego katalogu SEC. AAPL, GOOGL i GOOG działają także bez pobierania katalogu. Analizy obejmują obsługiwane spółki Nasdaq i NYSE raportujące w USD.</p>
    <div className="catalog"><label htmlFor="catalog-query">Szukaj w katalogu SEC</label><input id="catalog-query" value={catalogQuery} maxLength={64} onChange={event=>setCatalogQuery(event.target.value)} placeholder="Symbol lub nazwa spółki"/><button disabled={catalogBusy || pending || checking} onClick={()=>void searchCatalog()}>Szukaj w katalogu</button><button disabled={catalogBusy || pending || checking} onClick={()=>void searchCatalog(true)}>Pobierz katalog SEC</button>
    <p className="hint">Wyszukiwanie czyta lokalną kopię. Pobranie katalogu jest jawnym zapytaniem SEC i zużywa limit źródła.</p>
    {catalogBusy&&<p role="status">Wczytywanie katalogu…</p>}{catalogError&&<p role="alert">{catalogError}</p>}
    {catalog&&<><p>{catalog.retrieved_at ? 'Katalog pobrany '+new Date(catalog.retrieved_at).toLocaleString('pl-PL') : 'Brak pobranej kopii katalogu.'}</p>{catalog.items.length===0&&<p>Brak pasujących spółek w zapisanym katalogu.</p>}<div className="catalog-results">{catalog.items.map(item=><button key={item.symbol+item.cik+item.exchange_mic} disabled={!!attempt || pending || checking} onClick={()=>{setSymbol(item.symbol);setMarket(item.exchange_mic);}}>{item.symbol} · {item.display_name} · {item.exchange_mic}</button>)}</div></>}
    </div>
    <form onSubmit={event => {event.preventDefault(); void start();}}>
      <label htmlFor="analysis-market">Rynek</label>
      <select id="analysis-market" value={market ?? ''} disabled={!!attempt || pending || checking} onChange={event=>setMarket((event.target.value || null) as Market)}>
        <option value="">USA — automatycznie</option><option value="XNAS">Nasdaq</option><option value="XNYS">NYSE</option><option value="XWAR">GPW — adapter w przygotowaniu</option>
      </select>
      {market==='XWAR'&&<p role="status">GPW: przygotowujemy źródła raportów i identyfikację instrumentów. Analizy tego rynku nie są jeszcze dostępne. Nie zamienimy polskiego symbolu na spółkę z USA.</p>}
      <label htmlFor="analysis-symbol">Symbol spółki do analizy</label>
      <div><input id="analysis-symbol" value={symbol} disabled={!!attempt || pending} maxLength={16} onChange={event => setSymbol(event.target.value.toUpperCase())} autoComplete="off" />
      <button disabled={pending || checking || finished || market==='XWAR'}>{pending ? 'Zapisywanie zadania…' : attempt || history.some(item => attemptIdentity(item) === attemptIdentity({symbol:normalizeSymbol(symbol),exchange_mic:market})) ? 'Ponów to samo żądanie' : 'Zleć analizę'}</button></div>
    </form>
    <p className="hint">Nowe analizy obejmują przychód, wynik netto, gotówkę, składniki długu długoterminowego i przepływy pieniężne. Wolne przepływy obliczamy z zgodnych danych operacyjnych i nakładów. Zakres to roczne dane US-GAAP w USD; brak wymaganego zasobu SEC może zablokować analizę. Dane mogą być częściowe. Samo wyszukiwanie spółki nie uruchamia analizy.</p>
    {pending && <p role="status">Zapisujemy zlecenie w trwałej kolejce…</p>}
    {error && <p role="alert">{error}</p>}
    {result && <p role="status">{result.status === 'completed' ? 'Analiza zakończona. Jej zapisany raport jest widoczny poniżej.' : result.status === 'failed' ? 'Analiza zakończyła się błędem.' : result.status === 'queued' ? 'Zadanie zapisane. Oczekuje na dostępnego wykonawcę; możesz zamknąć kartę.' : 'Wykonawca przetwarza zadanie.'} {taskStages[result.stage]} · próba {result.attempt}. {result.error_reason}</p>}
    {result && !finished && poll >= 60 && <p className="hint">Automatyczny podgląd zatrzymany. Zadanie pozostaje zapisane; możesz ręcznie sprawdzić stan.</p>}
    {attempt && !pending && <div className="actions">
      {!finished && <button disabled={checking} onClick={() => {setPoll(0); void check(attempt);}}>{checking ? 'Sprawdzanie…' : 'Sprawdź stan'}</button>}
      {!finished && <button disabled={checking} onClick={parkAttempt}>Wybierz inną spółkę</button>}
      {finished && <button onClick={() => {setAttempt(undefined); remember(undefined); setResult(undefined); setError('');}}>Przygotuj kolejną analizę</button>}
    </div>}
    {attempt && !finished && !pending && <p className="hint">Zmiana spółki nie anuluje poprzedniej analizy. Zachowamy jej identyfikator, aby bezpiecznie wrócić do tego samego żądania.</p>}
    {!attempt && history.length > 0 && <div className="parked"><p>Niedokończone żądania w tej karcie:</p>{history.map(item => <button key={item.run_id} disabled={pending || checking} onClick={() => {setAttempt(item); remember(item); setSymbol(item.symbol); setMarket(item.exchange_mic ?? null); setResult(undefined); setError(''); setPoll(0);}}>Wróć do {item.symbol} · {marketLabel(item.exchange_mic)} · {item.run_id.slice(0,8)}</button>)}</div>}
    {attempt && <small>Identyfikator analizy: {attempt.run_id}</small>}
  </section>;
}

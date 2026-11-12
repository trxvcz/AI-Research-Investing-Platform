import {useEffect, useState} from 'react';
import {ImportTaskHistory} from './task-history';
import {marketLabel} from './launch-state';
import {completedAnalysis, taskStages, taskStatuses} from './task-state';
import type {TaskPage} from './task-state';
import type {StartedAnalysis} from './launch';

const time = (value: string|null) => value ? new Intl.DateTimeFormat('pl-PL', {dateStyle:'medium',timeStyle:'medium',timeZone:'UTC'}).format(new Date(value)) + ' UTC' : '—';
export function TaskMonitor({refreshKey, onOpen}: {refreshKey:number; onOpen:(analysis:StartedAnalysis)=>void}) {
  const [historyRun,setHistoryRun]=useState('');
  const [cursors,setCursors] = useState<string[]>(['']);
  const [retry,setRetry] = useState(0);
  const [poll,setPoll] = useState(0);
  const [data,setData] = useState<{cursor:string;page:TaskPage}>();
  const [error,setError] = useState('');
  const [loading,setLoading] = useState(false);
  const cursor = cursors[cursors.length-1];
  const page = data?.cursor === cursor ? data.page : undefined;
  useEffect(()=>setPoll(0),[refreshKey]);
  useEffect(() => {
    const abort = new AbortController();
    const timeout = setTimeout(() => {setError('Odczyt zadań trwa zbyt długo. Spróbuj ponownie.');setLoading(false);abort.abort();},30000);
    setLoading(true);setError('');
    const params = new URLSearchParams({limit:'20'});
    if(cursor) params.set('after_id',cursor);
    fetch('/v1/panel/tasks?'+params,{signal:abort.signal,cache:'no-store',headers:{Accept:'application/json'}})
      .then(async response => {if(!response.ok)throw Error(response.status===503?'Baza zadań jest niedostępna.':'Nie udało się odczytać zadań ('+response.status+').');return await response.json() as TaskPage;})
      .then(value => {if(!abort.signal.aborted)setData({cursor,page:value});})
      .catch(failure => {if(!abort.signal.aborted)setError(failure instanceof TypeError?'Brak połączenia z lokalnym panelem.':(failure as Error).message);})
      .finally(() => {clearTimeout(timeout);if(!abort.signal.aborted)setLoading(false);});
    return () => {clearTimeout(timeout);abort.abort();};
  },[cursor,retry,poll,refreshKey]);
  useEffect(() => {
    if(error || loading || poll>=60 || !page?.items.some(task=>task.status==='queued'||task.status==='running'))return;
    const timer = setTimeout(()=>setPoll(n=>n+1),5000);
    return ()=>clearTimeout(timer);
  },[page,error,loading,poll]);
  return <section className="task-monitor" aria-labelledby="tasks-title">
    <h2 id="tasks-title">Zadania i wykonawcy</h2>
    <p>Trwałe zlecenia przygotowania danych i analiz. Oczekujące zadanie pozostaje zapisane również po zamknięciu panelu. Wykonawca musi być uruchomiony osobno.</p>
    <button disabled={loading} onClick={()=>{setPoll(0);setRetry(n=>n+1);}}>Odśwież zadania</button>
    {loading&&<p role="status">Sprawdzanie zadań…</p>}
    {error&&<p role="alert">{error}</p>}
    {page?.items.length===0&&<p>Nie ma jeszcze zleceń w tej kolejce.</p>}
    {page&&page.items.length>0&&<div className="task-table"><table><thead><tr><th>Spółka i zadanie</th><th>Stan i etap</th><th>Wykonawca</th><th>Wynik</th></tr></thead><tbody>{page.items.map(task=>{
      const result = completedAnalysis(task);
      return <tr key={task.run_id}><th scope="row">{task.symbol} · {marketLabel(task.exchange_mic)}<small>{task.run_id}</small><small>Zlecono {time(task.created_at)}</small></th>
        <td>{taskStatuses[task.status]}<small>{taskStages[task.stage]} · próba {task.attempt}</small><small>Aktualizacja {time(task.updated_at)}</small>{task.status==='queued'&&<small>Oczekuje na dostępnego wykonawcę.</small>}</td>
        <td>{task.worker_id??'Jeszcze nie przydzielono'}<small>Ostatni sygnał: {time(task.heartbeat_at)}</small><small>Uprawnienie do wykonania do: {time(task.lease_expires_at)}</small></td>
        <td><button onClick={()=>setHistoryRun(task.run_id)}>Historia etapów</button>{result&&<button onClick={()=>onOpen(result)}>Otwórz raport</button>}{task.error_reason&&<p>{task.error_reason}</p>}{task.error_code&&<small>Kod: {task.error_code}</small>}{!result&&!task.error_reason&&'Raport jeszcze niedostępny'}</td>
      </tr>;
    })}</tbody></table></div>}
    {poll>=60&&<p className="hint">Automatyczny podgląd zatrzymany. Użyj „Odśwież zadania”, aby ponownie sprawdzić stan.</p>}
    {(cursors.length>1||page?.next_after_id)&&<nav aria-label="Strony zadań"><button disabled={cursors.length<=1||loading} onClick={()=>{setPoll(0);setCursors(values=>values.slice(0,-1));}}>← Wstecz</button><button disabled={!page?.next_after_id||loading} onClick={()=>{if(page?.next_after_id){setPoll(0);setCursors(values=>[...values,page.next_after_id!]);}}}>Dalej →</button></nav>}
    {historyRun&&<ImportTaskHistory key={historyRun} runId={historyRun} refreshKey={`${retry}:${poll}:${refreshKey}`}/>}
    <p className="hint">Etapy pokazują rzeczywistą pracę importera i workera analitycznego. Nie oznaczają uruchomienia modeli ani agentów LLM.</p>
  </section>;
}

import {useEffect,useRef,useState} from 'react';
import {assertDocumentTaskDetail,assertDocumentTaskIdentity,documentTaskAttempt,documentTaskRefreshIdentity,documentTaskStages,documentTaskStatuses,shouldPollDocumentTasks} from './document-task-state';
import type {DocumentTaskCreate,DocumentTaskDetail,DocumentTaskPage,DocumentTaskRecord} from './document-task-state';

const base='/v1/panel/document-tasks';
const time=(value:string|null)=>value?new Intl.DateTimeFormat('pl-PL',{dateStyle:'medium',timeStyle:'medium',timeZone:'UTC'}).format(new Date(value))+' UTC':'—';
class TaskFailure extends Error{
  status:number;
  constructor(status:number){super(status===503?'Kolejka dokumentów jest niedostępna.':status===404?'Nie znaleziono zadania lub dokumentu.':status===409?'Identyfikator zadania ma już inne zamrożone dane.':'Nie udało się wykonać operacji ('+status+').');this.status=status;}
}
async function response<T>(res:Response):Promise<T>{if(!res.ok)throw new TaskFailure(res.status);return await res.json() as T;}
const failureText=(error:unknown)=>error instanceof TaskFailure?error.message:'Nie potwierdzono wyniku operacji. Sprawdź połączenie lub ponów tę samą próbę.';

export function QueueDocumentTask({archiveId,onQueued}:{archiveId:string;onQueued?:()=>void}){
  const [pending,setPending]=useState<DocumentTaskCreate>();
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[saved,setSaved]=useState('');
  const lock=useRef(false),mounted=useRef(true),controller=useRef<AbortController|undefined>(undefined);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;controller.current?.abort();};},[]);
  const submit=async()=>{
    if(lock.current)return;
    lock.current=true;setBusy(true);setError('');
    const attempt=documentTaskAttempt(archiveId,pending,()=>crypto.randomUUID());
    setPending(attempt);
    const abort=new AbortController();controller.current=abort;const timer=setTimeout(()=>abort.abort(),30000);
    try{
      const task=await fetch(base,{method:'POST',headers:{'Content-Type':'application/json','X-Alphasense-Panel':'1',Accept:'application/json'},body:JSON.stringify(attempt),signal:abort.signal}).then(response<DocumentTaskRecord>);
      assertDocumentTaskIdentity(task,attempt);
      if(mounted.current){setPending(undefined);setSaved(task.job_id);onQueued?.();}
    }catch(failure){if(mounted.current){setError(failureText(failure));if(failure instanceof TaskFailure&&[400,403,413,422].includes(failure.status))setPending(undefined);}}
    finally{clearTimeout(timer);if(mounted.current){lock.current=false;setBusy(false);}}
  };
  return <section className="document-queue-command" aria-label="Weryfikacja dokumentu w tle">
    <p>Weryfikacja w tle ponownie sprawdza zapisany szkic i cytaty. Nie generuje nowej analizy LLM ani nie publikuje faktów w raportach.</p>
    {!saved&&<button disabled={busy} onClick={()=>void submit()}>{busy?'Zapisywanie zlecenia…':pending?'Ponów to samo zlecenie':'Zleć weryfikację w tle'}</button>}
    {pending&&<p>Identyfikator próby: <code>{pending.job_id}</code>. Ponowienie zachowuje ten sam dokument i identyfikator. Po przeładowaniu strony najpierw sprawdź kolejkę.</p>}
    {saved&&<p role="status">Zapisano zadanie <code>{saved}</code>. <a href="#document-task-title">Sprawdź kolejkę dokumentów</a>.</p>}
    {error&&<p role="alert">{error}</p>}
  </section>;
}

export function DocumentTaskMonitor({refreshKey=0}:{refreshKey?:number}){
  const [cursors,setCursors]=useState<string[]>(['']),[retry,setRetry]=useState(0),[poll,setPoll]=useState(0);
  const [data,setData]=useState<{cursor:string;page:DocumentTaskPage}>(),[error,setError]=useState(''),[loading,setLoading]=useState(false),[selected,setSelected]=useState('');
  const cursor=cursors[cursors.length-1],page=data?.cursor===cursor?data.page:undefined;
  useEffect(()=>setPoll(0),[refreshKey]);
  useEffect(()=>{
    const abort=new AbortController();const timer=setTimeout(()=>{setError('Odczyt kolejki trwa zbyt długo. Odśwież zadania.');setLoading(false);abort.abort();},30000);
    setLoading(true);setError('');
    const params=new URLSearchParams({limit:'10'});if(cursor)params.set('after_id',cursor);
    fetch(base+'?'+params,{signal:abort.signal,cache:'no-store',headers:{Accept:'application/json'}}).then(response<DocumentTaskPage>)
      .then(value=>{if(!abort.signal.aborted)setData({cursor,page:value});})
      .catch(failure=>{if(!abort.signal.aborted)setError(failureText(failure));})
      .finally(()=>{clearTimeout(timer);if(!abort.signal.aborted)setLoading(false);});
    return()=>{clearTimeout(timer);abort.abort();};
  },[cursor,retry,poll,refreshKey]);
  useEffect(()=>{
    if(loading||!page||!shouldPollDocumentTasks(page.items,poll,error))return;
    const timer=setTimeout(()=>setPoll(n=>n+1),5000);return()=>clearTimeout(timer);
  },[page,loading,poll,error]);
  const refresh=()=>{setPoll(0);setRetry(n=>n+1);};
  return <section className="document-task-monitor" aria-labelledby="document-task-title">
    <h2 id="document-task-title">Kolejka dokumentów</h2>
    <p>Osobny worker odtwarza weryfikację zapisanych szkiców. Zlecenie zostaje w PostgreSQL po zamknięciu panelu. Ekstrakcja modelem pozostaje wyłączona.</p>
    <button disabled={loading} onClick={refresh}>Odśwież zadania dokumentów</button>
    {loading&&<p role="status">Sprawdzanie kolejki dokumentów…</p>}{error&&<p role="alert">{error}</p>}
    {page?.items.length===0&&<p>Nie ma jeszcze zadań dokumentowych na tej stronie.</p>}
    {page&&page.items.length>0&&<div className="task-table"><table><thead><tr><th>Dokument i zadanie</th><th>Stan i etap</th><th>Wykonawca</th><th>Szczegóły</th></tr></thead><tbody>{page.items.map(task=><tr key={task.job_id}>
      <th scope="row">{task.title}<small>{task.job_id}</small><small>Zlecono {time(task.created_at)}</small></th>
      <td>{documentTaskStatuses[task.status]}<small>{documentTaskStages[task.stage]} · próba {task.attempt}</small><small>{task.mode==='validate_saved_draft'?'Weryfikacja offline':'Ekstrakcja modelem — nieaktywna'}</small>{task.error_code&&<small>Kod: {task.error_code}</small>}</td>
      <td>{task.worker_id??'Jeszcze nie przydzielono'}<small>Ostatni sygnał: {time(task.heartbeat_at)}</small><small>Uprawnienie do wykonania do {time(task.lease_expires_at)}</small></td>
      <td><button onClick={()=>setSelected(task.job_id)}>Historia i audyt</button></td>
    </tr>)}</tbody></table></div>}
    {poll>=29&&<p>Automatyczny podgląd zatrzymany po 30 odczytach. Użyj przycisku, aby sprawdzić stan ponownie.</p>}
    {(cursors.length>1||page?.next_after_id)&&<nav aria-label="Strony zadań dokumentowych"><button disabled={loading||cursors.length===1} onClick={()=>{setPoll(0);setCursors(values=>values.slice(0,-1));}}>← Wstecz</button><button disabled={loading||!page?.next_after_id} onClick={()=>{if(page?.next_after_id){setPoll(0);setCursors(values=>[...values,page.next_after_id!]);}}}>Dalej →</button></nav>}
    {selected&&<TaskDetails key={selected} jobId={selected} refreshKey={documentTaskRefreshIdentity(retry,poll,refreshKey)} onRefresh={refresh} onReadError={()=>setError('Automatyczny podgląd zatrzymany po błędzie odczytu audytu. Odśwież zadania.')}/>}
  </section>;
}

function TaskDetails({jobId,refreshKey,onRefresh,onReadError}:{jobId:string;refreshKey:string;onRefresh:()=>void;onReadError:()=>void}){
  const [detail,setDetail]=useState<DocumentTaskDetail>(),[error,setError]=useState('');
  useEffect(()=>{
    const abort=new AbortController();const timer=setTimeout(()=>{setError('Odczyt audytu trwa zbyt długo. Odśwież zadania.');onReadError();abort.abort();},30000);setDetail(undefined);setError('');
    fetch(base+'/'+encodeURIComponent(jobId),{signal:abort.signal,cache:'no-store',headers:{Accept:'application/json'}}).then(response<DocumentTaskDetail>)
      .then(value=>{assertDocumentTaskDetail(value,jobId);if(!abort.signal.aborted)setDetail(value);})
      .catch(failure=>{if(!abort.signal.aborted){setError(failureText(failure));onReadError();}}).finally(()=>clearTimeout(timer));
    return()=>{clearTimeout(timer);abort.abort();};
  },[jobId,refreshKey]);
  if(error)return <div role="alert"><p>{error}</p><button onClick={onRefresh}>Odśwież audyt</button></div>;
  if(!detail)return <p role="status">Wczytywanie historii zadania…</p>;
  const task=detail.task;
  return <article aria-labelledby="document-task-detail-title"><h3 id="document-task-detail-title">Historia: {task.title}</h3><p>{documentTaskStatuses[task.status]} · {documentTaskStages[task.stage]}</p>
    <p>Zadanie <code>{task.job_id}</code>; dokument <code>{task.archive_id}</code>.</p><a href="#document-archive-title">Przejdź do archiwum szkiców</a>
    <details><summary>Hashe zamrożonego wejścia</summary><p>Dokument: <code>{task.document_sha256}</code></p><p>Szkic: <code>{task.draft_sha256}</code></p><p>Wejście zadania: <code>{task.input_sha256}</code></p></details>
    <h4>Przebieg etapów</h4><ol>{detail.events.map(event=><li key={event.sequence}>{documentTaskStages[event.stage]} · próba {event.attempt} · {time(event.recorded_at)}{event.error_code&&' · '+event.error_code}</li>)}</ol>
    <h4>Audyt prób</h4>{detail.audits.length===0&&<p>Nie zakończono jeszcze żadnej próby.</p>}{detail.audits.map(audit=><details key={audit.attempt}><summary>Próba {audit.attempt} · {audit.outcome==='completed'?'Zakończona':audit.outcome==='blocked'?'Zablokowana':audit.outcome==='interrupted'?'Przerwana':'Błąd'}</summary>
      <p>Wykonawca {audit.worker_id}; od {time(audit.started_at)} do {time(audit.finished_at)}.</p><p>{audit.execution==='offline-validation-v1'?'Weryfikacja istniejącego szkicu offline.':'Wywołanie modelu zablokowane.'} Dostawca nie został wywołany. Tokeny, model i prompt: nie dotyczy. Koszt API: {audit.cost_usd} USD.</p>
      {audit.error_code&&<p>Kod: {audit.error_code}</p>}<p>Implementacja: <code>{audit.implementation_sha256}</code></p><p>Żądanie: <code>{audit.request_sha256}</code></p><p>Wynik: <code>{audit.output_sha256??'brak wyniku'}</code></p>
      {audit.result&&<p>Walidacja: {audit.result.status==='needs_review'?'wymaga przeglądu semantycznego':audit.result.status==='rejected'?'szkic odrzucony':'zablokowana'} · {audit.result.facts.length} faktów. Wynik pozostaje szkicem.</p>}
    </details>)}
  </article>;
}

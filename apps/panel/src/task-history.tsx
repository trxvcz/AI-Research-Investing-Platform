import {useEffect,useState} from 'react';
import {assertTaskEvents} from './schedule-state';
import type {TaskEventPage} from './schedule-state';
import {taskStages,taskStatuses} from './task-state';

const time=(value:string)=>new Intl.DateTimeFormat('pl-PL',{dateStyle:'medium',timeStyle:'medium',timeZone:'UTC'}).format(new Date(value))+' UTC';
export function ImportTaskHistory({runId,refreshKey}:{runId:string;refreshKey:string}){
  const [stack,setStack]=useState<number[]>([0]),[retry,setRetry]=useState(0);
  const [data,setData]=useState<{after:number;page:TaskEventPage}>(),[error,setError]=useState(''),[loading,setLoading]=useState(false);
  const after=stack[stack.length-1],page=data?.after===after?data.page:undefined;
  useEffect(()=>{
    const abort=new AbortController();setLoading(true);setError('');
    const timeout=setTimeout(()=>{setError('Odczyt historii trwa zbyt długo. Odśwież dane.');setLoading(false);abort.abort();},30000);
    fetch('/v1/panel/tasks/'+encodeURIComponent(runId)+'/events?'+new URLSearchParams({after_sequence:String(after),limit:'50'}),{signal:abort.signal,cache:'no-store',headers:{Accept:'application/json'}})
      .then(async response=>{if(!response.ok)throw Error(response.status===503?'Historia jest chwilowo niedostępna.':'Nie udało się odczytać historii zadania.');return await response.json() as TaskEventPage;})
      .then(value=>{assertTaskEvents(value,runId,after);if(!abort.signal.aborted)setData({after,page:value});})
      .catch(failure=>{if(!abort.signal.aborted)setError(failure instanceof TypeError?'Brak połączenia z lokalnym panelem.':String(failure.message));})
      .finally(()=>{clearTimeout(timeout);if(!abort.signal.aborted)setLoading(false);});
    return()=>{clearTimeout(timeout);abort.abort();};
  },[runId,after,retry,refreshKey]);
  return <article aria-labelledby="import-task-history-title"><h3 id="import-task-history-title">Historia etapów importu SEC</h3><p>Zadanie <code>{runId}</code>. Sygnały heartbeat nie tworzą osobnych etapów.</p><button disabled={loading} onClick={()=>setRetry(n=>n+1)}>Odśwież historię etapów</button>
    {loading&&<p role="status">Wczytywanie etapów…</p>}{error&&<p role="alert">{error}</p>}
    {page?.coverage==='legacy_snapshot'&&<p>Historia starszego zadania jest niepełna. Zachowano stan znany w chwili migracji; wcześniejszych etapów i ich czasów nie odtworzono.</p>}
    {page?.items.length===0&&<p>Brak wydarzeń na tej stronie.</p>}
    {page&&<ol start={after+1}>{page.items.map(event=><li key={event.sequence}><b>{event.kind==='legacy_snapshot'?'Zapis zastanego stanu':taskStages[event.task.stage]}</b> · {time(event.recorded_at)}<p>{taskStatuses[event.task.status]} · próba {event.task.attempt} · wykonawca {event.task.worker_id??'nieprzydzielony'}</p>{event.task.error_reason&&<p>{event.task.error_reason}</p>}{event.task.error_code&&<small>Kod: {event.task.error_code}</small>}{event.task.report_id&&<small>Raport {event.task.report_id} · rewizja {event.task.revision}</small>}</li>)}</ol>}
    {(stack.length>1||page?.next_after_sequence!==null)&&page&&<nav aria-label="Strony historii importu"><button disabled={loading||stack.length===1} onClick={()=>setStack(values=>values.slice(0,-1))}>← Wstecz</button><button disabled={loading||page.next_after_sequence===null} onClick={()=>{if(page.next_after_sequence!==null)setStack(values=>[...values,page.next_after_sequence!]);}}>Dalej →</button></nav>}
  </article>;
}

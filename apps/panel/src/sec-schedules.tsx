import {useEffect,useRef,useState} from 'react';
import {explicitTimestamp} from './document-archive-state';
import {assertOccurrences,assertScheduleCommand,assertScheduleCreated,hoursToInterval,scheduleAttempt,scheduleReadIdentity,shouldPollSchedules} from './schedule-state';
import type {OccurrencePage,ScheduleCommand,ScheduleCreate,SchedulePage,ScheduleRecord} from './schedule-state';

const base='/v1/panel/schedules';
const headers={'Content-Type':'application/json','X-Alphasense-Panel':'1',Accept:'application/json'};
const time=(value:string|null)=>value?new Intl.DateTimeFormat('pl-PL',{dateStyle:'medium',timeStyle:'medium',timeZone:'UTC'}).format(new Date(value))+' UTC':'—';
class ScheduleFailure extends Error{status:number;constructor(status:number){super(status===409?'Stan lub tożsamość harmonogramu uległy zmianie. Odśwież dane.':status===422?'Sprawdź symbol, rynek, odstęp i datę harmonogramu.':status===503?'Magazyn harmonogramów jest niedostępny.':'Nie udało się wykonać operacji ('+status+').');this.status=status;}}
async function response<T>(result:Response):Promise<T>{if(!result.ok)throw new ScheduleFailure(result.status);return await result.json() as T;}
const failureText=(failure:unknown)=>failure instanceof ScheduleFailure?failure.message:'Nie potwierdzono wyniku operacji. Sprawdź połączenie i ponów tę samą próbę.';

export function SecSchedules(){
  const [stack,setStack]=useState<string[]>(['']),[retry,setRetry]=useState(0),[poll,setPoll]=useState(0),[selected,setSelected]=useState('');
  const [data,setData]=useState<{cursor:string;page:SchedulePage}>(),[loading,setLoading]=useState(false),[error,setError]=useState('');
  const cursor=stack[stack.length-1],page=data?.cursor===cursor?data.page:undefined;
  useEffect(()=>{
    const abort=new AbortController();setLoading(true);setError('');
    const timeout=setTimeout(()=>{setError('Odczyt harmonogramów trwa zbyt długo. Odśwież dane.');setLoading(false);abort.abort();},30000);
    const query=new URLSearchParams({limit:'10'});if(cursor)query.set('after_id',cursor);
    fetch(base+'?'+query,{signal:abort.signal,cache:'no-store',headers:{Accept:'application/json'}}).then(response<SchedulePage>)
      .then(value=>{if(!abort.signal.aborted)setData({cursor,page:value});})
      .catch(failure=>{if(!abort.signal.aborted)setError(failureText(failure));})
      .finally(()=>{clearTimeout(timeout);if(!abort.signal.aborted)setLoading(false);});
    return()=>{clearTimeout(timeout);abort.abort();};
  },[cursor,retry,poll]);
  useEffect(()=>{
    if(loading||!page||!shouldPollSchedules(page.items.some(item=>item.enabled),poll,error))return;
    const timer=setTimeout(()=>setPoll(n=>n+1),5000);return()=>clearTimeout(timer);
  },[loading,page,poll,error]);
  const refresh=()=>{setPoll(0);setRetry(n=>n+1);};
  return <section className="sec-schedules" aria-labelledby="sec-schedules-title"><h2 id="sec-schedules-title">Harmonogramy analiz SEC</h2>
    <p>Wybierz spółkę, odstęp i pierwszy termin. Scheduler zapisuje zlecenia w kolejce PostgreSQL; importer nadal sprawdza politykę źródła i limity SEC. Harmonogram nie wywołuje Gemini.</p>
    <CreateSchedule onCreated={id=>{setStack(['']);setSelected(id);refresh();}}/>
    <h3>Zapisane harmonogramy</h3><button disabled={loading} onClick={refresh}>Odśwież harmonogramy</button>
    {loading&&<p role="status">Sprawdzanie harmonogramów…</p>}{error&&<p role="alert">{error}</p>}
    {page?.items.length===0&&<p>Brak harmonogramów na tej stronie.</p>}
    {page&&page.items.length>0&&<div className="task-table"><table><thead><tr><th>Spółka i tryb</th><th>Terminy</th><th>Stan</th><th>Działania</th></tr></thead><tbody>{page.items.map(record=><tr key={record.schedule_id}>
      <th scope="row">{record.template.symbol} · {record.template.exchange_mic}<small>{record.schedule_id}</small><small>{record.template.pipeline_version}</small><small>{record.template.refresh?'Nowe pobrania SEC w limitach':'Odtwarzanie z archiwum, pobranie gdy brakuje źródła'}</small></th>
      <td>Co {record.interval_seconds/3600} godz.<small>Pierwszy termin {time(record.first_run_at)}</small><small>Następny termin {time(record.next_run_at)}</small><small>Ostatni obsłużony termin {time(record.last_scheduled_for)}</small></td>
      <td>{record.enabled?'Włączony':'Wstrzymany'}<small>Rewizja ustawienia {record.revision}</small><small>{record.last_outcome==='enqueued'?'Zlecenie zapisane':record.last_outcome==='skipped_busy'?'Termin pominięty — trwa inne zadanie':'Nie obsłużono jeszcze terminu'}</small>{record.last_run_id&&<small>Ostatnie zadanie {record.last_run_id}</small>}</td>
      <td><ScheduleControl record={record} onChanged={refresh}/><button onClick={()=>setSelected(record.schedule_id)}>Historia terminów</button></td>
    </tr>)}</tbody></table></div>}
    {(stack.length>1||page?.next_after_id)&&<nav aria-label="Strony harmonogramów"><button disabled={loading||stack.length===1} onClick={()=>{setPoll(0);setStack(values=>values.slice(0,-1));}}>← Wstecz</button><button disabled={loading||!page?.next_after_id} onClick={()=>{if(page?.next_after_id){setPoll(0);setStack(values=>[...values,page.next_after_id!]);}}}>Dalej →</button></nav>}
    {poll>=29&&<p>Automatyczny podgląd zatrzymany po 30 odczytach. Użyj odświeżenia, aby sprawdzić nowe terminy.</p>}
    {selected&&<OccurrenceHistory key={selected} scheduleId={selected} refreshKey={scheduleReadIdentity(retry,poll)}/>}
  </section>;
}

function CreateSchedule({onCreated}:{onCreated:(id:string)=>void}){
  const [symbol,setSymbol]=useState(''),[market,setMarket]=useState<'XNAS'|'XNYS'>('XNAS'),[hours,setHours]=useState('24'),[first,setFirst]=useState(()=>new Date().toISOString()),[refresh,setRefresh]=useState(false);
  const [pending,setPending]=useState<ScheduleCreate>(),[busy,setBusy]=useState(false),[error,setError]=useState(''),[saved,setSaved]=useState('');
  const lock=useRef(false),mounted=useRef(true),controller=useRef<AbortController|undefined>(undefined);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;controller.current?.abort();};},[]);
  const submit=async()=>{
    if(lock.current)return;lock.current=true;setBusy(true);setError('');setSaved('');
    let timer:ReturnType<typeof setTimeout>|undefined;
    let attemptedNetwork=false;
    try{
      let attempt=pending;
      if(!attempt){
        const normalized=symbol.trim().toUpperCase();if(!/^[A-Z0-9][A-Z0-9.-]{0,15}$/.test(normalized))throw Error('Podaj poprawny symbol spółki z katalogu SEC.');
        attempt=scheduleAttempt({symbol:normalized,exchange_mic:market,interval_seconds:hoursToInterval(hours),first_run_at:explicitTimestamp(first),enabled:false,refresh},undefined,()=>crypto.randomUUID());
        setPending(attempt);
      }
      const abort=new AbortController();controller.current=abort;timer=setTimeout(()=>abort.abort(),30000);
      attemptedNetwork=true;
      const record=await fetch(base,{method:'POST',headers,body:JSON.stringify(attempt),signal:abort.signal}).then(response<ScheduleRecord>);
      assertScheduleCreated(record,attempt);
      if(mounted.current){setPending(undefined);setSaved('Zapisano harmonogram. Jego bieżący stan jest widoczny na liście; nowy harmonogram jest początkowo wstrzymany.');onCreated(record.schedule_id);}
    }catch(failure){if(mounted.current){setError(failure instanceof ScheduleFailure?failure.message:pending||attemptedNetwork?failureText(failure):failure instanceof Error?failure.message:'Sprawdź dane.');if(failure instanceof ScheduleFailure&&[400,403,413,422].includes(failure.status))setPending(undefined);}}
    finally{if(timer)clearTimeout(timer);if(mounted.current){lock.current=false;setBusy(false);}}
  };
  return <details><summary>Dodaj harmonogram</summary><form onSubmit={event=>{event.preventDefault();void submit();}}><fieldset disabled={busy||!!pending}><legend>Nowy harmonogram — początkowo wstrzymany</legend>
    <label htmlFor="schedule-symbol">Symbol SEC</label><input id="schedule-symbol" required maxLength={16} value={symbol} onChange={event=>setSymbol(event.target.value)} placeholder="Np. GOOGL"/>
    <label htmlFor="schedule-market">Rynek</label><select id="schedule-market" value={market} onChange={event=>setMarket(event.target.value as 'XNAS'|'XNYS')}><option value="XNAS">Nasdaq</option><option value="XNYS">NYSE</option></select>
    <label htmlFor="schedule-hours">Odstęp w pełnych godzinach</label><input id="schedule-hours" type="number" min={1} max={720} step={1} required value={hours} onChange={event=>setHours(event.target.value)}/>
    <label htmlFor="schedule-first">Pierwszy termin ze strefą</label><input id="schedule-first" required value={first} onChange={event=>setFirst(event.target.value)} placeholder="2026-11-10T18:00:00+01:00"/>
    <p>Podaj sekundy i strefę, np. Z lub +01:00. Po przerwie scheduler obsłuży najwyżej jeden ostatni należny termin; pozostałe oznaczy jako pominięte.</p>
    <label><input type="checkbox" checked={refresh} onChange={event=>setRefresh(event.target.checked)}/> Pobieraj nowe dane SEC w limitach</label><p>Bez zaznaczenia importer korzysta z archiwum i pobiera brakujące źródła. Włączenie odświeżania zużywa limit darmowego źródła; nie uruchamia płatnego fallbacku.</p>
  </fieldset><button disabled={busy}>{busy?'Zapisywanie…':pending?'Ponów ten sam zapis':'Zapisz wstrzymany harmonogram'}</button>
  {pending&&<><p>Próba {pending.schedule_id}. Po utracie odpowiedzi ponowienie zachowuje ten sam identyfikator. Po przeładowaniu strony sprawdź listę przed osobnym zapisem.</p><button type="button" disabled={busy} onClick={()=>{setPending(undefined);setError('');}}>Rozpocznij osobny harmonogram</button><p>Poprzedni zapis może już istnieć.</p></>}
  </form>{error&&<p role="alert">{error}</p>}{saved&&<p role="status">{saved}</p>}</details>;
}

function ScheduleControl({record,onChanged}:{record:ScheduleRecord;onChanged:()=>void}){
  const [pending,setPending]=useState<ScheduleCommand>(),[busy,setBusy]=useState(false),[error,setError]=useState(''),[conflict,setConflict]=useState<number>();
  const lock=useRef(false),mounted=useRef(true),controller=useRef<AbortController|undefined>(undefined);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;controller.current?.abort();};},[]);
  useEffect(()=>{if(conflict!==undefined&&record.revision!==conflict)setConflict(undefined);},[record.revision,conflict]);
  const submit=async()=>{
    if(lock.current||conflict!==undefined)return;lock.current=true;setBusy(true);setError('');
    const command=pending??{command_id:crypto.randomUUID(),expected_revision:record.revision,enabled:!record.enabled};setPending(command);
    const abort=new AbortController();controller.current=abort;const timer=setTimeout(()=>abort.abort(),30000);
    try{
      const current=await fetch(base+'/'+encodeURIComponent(record.schedule_id)+'/commands',{method:'POST',headers,body:JSON.stringify(command),signal:abort.signal}).then(response<ScheduleRecord>);
      assertScheduleCommand(current,record.schedule_id,command);
      if(mounted.current){setPending(undefined);onChanged();}
    }catch(failure){if(mounted.current){setError(failureText(failure));if(failure instanceof ScheduleFailure&&failure.status===409){setConflict(record.revision);setPending(undefined);}else if(failure instanceof ScheduleFailure&&[400,403,413,422].includes(failure.status))setPending(undefined);}}
    finally{clearTimeout(timer);if(mounted.current){lock.current=false;setBusy(false);}}
  };
  return <div><button disabled={busy||conflict!==undefined||record.revision>=10000} onClick={()=>void submit()}>{busy?'Zapisywanie…':pending?'Ponów tę samą zmianę':record.enabled?'Wstrzymaj':'Włącz'}</button>{pending&&<small>Zmiana {pending.command_id}; ponowienie zachowuje identyfikator.</small>}{error&&<p role="alert">{error}</p>}{conflict!==undefined&&<button onClick={onChanged}>Odśwież przed kolejną zmianą</button>}</div>;
}

function OccurrenceHistory({scheduleId,refreshKey}:{scheduleId:string;refreshKey:string}){
  const [stack,setStack]=useState<number[]>([0]),[retry,setRetry]=useState(0),[data,setData]=useState<{after:number;page:OccurrencePage}>(),[error,setError]=useState(''),[loading,setLoading]=useState(false);
  const after=stack[stack.length-1],page=data?.after===after?data.page:undefined;
  useEffect(()=>{
    const abort=new AbortController();setLoading(true);setError('');const timer=setTimeout(()=>{setError('Odczyt terminów trwa zbyt długo. Odśwież historię.');setLoading(false);abort.abort();},30000);
    fetch(base+'/'+encodeURIComponent(scheduleId)+'/occurrences?'+new URLSearchParams({after_sequence:String(after),limit:'20'}),{signal:abort.signal,cache:'no-store',headers:{Accept:'application/json'}}).then(response<OccurrencePage>)
      .then(value=>{assertOccurrences(value,scheduleId,after);if(!abort.signal.aborted)setData({after,page:value});})
      .catch(failure=>{if(!abort.signal.aborted)setError(failureText(failure));})
      .finally(()=>{clearTimeout(timer);if(!abort.signal.aborted)setLoading(false);});
    return()=>{clearTimeout(timer);abort.abort();};
  },[scheduleId,after,retry,refreshKey]);
  return <article><h3>Historia terminów</h3><p>Harmonogram <code>{scheduleId}</code>. Zapis zlecenia nie oznacza ukończonej analizy.</p><button disabled={loading} onClick={()=>setRetry(n=>n+1)}>Odśwież historię terminów</button>{loading&&<p role="status">Wczytywanie terminów…</p>}{error&&<p role="alert">{error}</p>}{page?.items.length===0&&<p>Nie obsłużono jeszcze terminów na tej stronie.</p>}{page&&<ol start={after+1}>{page.items.map(event=><li key={event.sequence}><b>{event.outcome==='enqueued'?'Zlecenie zapisane':'Pominięto — trwa inne zadanie'}</b><p>Termin {time(event.scheduled_for)} · obsłużono {time(event.dispatched_at)}</p><small>Pominięte wcześniejsze terminy: {event.skipped_slots}</small>{event.run_id&&<small>Zadanie {event.run_id} — sprawdź kolejkę analiz SEC.</small>}</li>)}</ol>}
  {page&&(stack.length>1||page.next_after_sequence!==null)&&<nav aria-label="Strony terminów"><button disabled={loading||stack.length===1} onClick={()=>setStack(values=>values.slice(0,-1))}>← Wstecz</button><button disabled={loading||page.next_after_sequence===null} onClick={()=>{if(page.next_after_sequence!==null)setStack(values=>[...values,page.next_after_sequence!]);}}>Dalej →</button></nav>}
  </article>;
}

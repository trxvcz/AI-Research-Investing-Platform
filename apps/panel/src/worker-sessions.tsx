import {useEffect,useState} from 'react';
import {assertWorkerPage,observedWorkerStatus,shouldPollWorkerSessions,workerKinds,workerPageIdentity,workerStatuses,workerStopReasons} from './worker-session-state';
import type {WorkerFilter,WorkerSessionPage} from './worker-session-state';

const time=(value:string|null)=>value?new Intl.DateTimeFormat('pl-PL',{dateStyle:'medium',timeStyle:'medium',timeZone:'UTC'}).format(new Date(value))+' UTC':'—';

export function WorkerSessions(){
  const [navigation,setNavigation]=useState<{kind:WorkerFilter;cursors:string[]}>({kind:'',cursors:['']});
  const [retry,setRetry]=useState(0),[poll,setPoll]=useState(0),[paused,setPaused]=useState(false);
  const [data,setData]=useState<{identity:string;page:WorkerSessionPage;requestedAt:number}>();
  const [error,setError]=useState(''),[loading,setLoading]=useState(false),[clock,setClock]=useState(()=>performance.now());
  const cursor=navigation.cursors[navigation.cursors.length-1],identity=workerPageIdentity(navigation.kind,cursor);
  const snapshot=data?.identity===identity?data:undefined;
  useEffect(()=>{const timer=setInterval(()=>setClock(performance.now()),1000);return()=>clearInterval(timer);},[]);
  useEffect(()=>{
    const abort=new AbortController(),requestedAt=performance.now();
    const timeout=setTimeout(()=>{setError('Odczyt rejestru trwa zbyt długo. Stan procesów jest niepotwierdzony.');setLoading(false);abort.abort();},30000);
    setLoading(true);setError('');
    const params=new URLSearchParams({limit:'10'});if(cursor)params.set('after_id',cursor);if(navigation.kind)params.set('kind',navigation.kind);
    fetch('/v1/panel/workers?'+params,{signal:abort.signal,cache:'no-store',headers:{Accept:'application/json'}})
      .then(async response=>{if(!response.ok)throw Error(response.status===503?'Rejestr wykonawców jest niedostępny.':'Nie udało się odczytać rejestru ('+response.status+').');return await response.json() as WorkerSessionPage;})
      .then(page=>{assertWorkerPage(page,navigation.kind);if(!abort.signal.aborted){setData({identity,page,requestedAt});setClock(performance.now());}})
      .catch(failure=>{if(!abort.signal.aborted)setError(failure instanceof TypeError?'Brak połączenia z rejestrem. Stan procesów jest niepotwierdzony.':(failure as Error).message);})
      .finally(()=>{clearTimeout(timeout);if(!abort.signal.aborted)setLoading(false);});
    return()=>{clearTimeout(timeout);abort.abort();};
  },[identity,retry,poll]);
  useEffect(()=>{
    if(loading||!snapshot||!shouldPollWorkerSessions(poll,error,paused))return;
    const timer=setTimeout(()=>setPoll(n=>n+1),5000);return()=>clearTimeout(timer);
  },[snapshot,loading,poll,error,paused]);
  const refresh=()=>{setLoading(true);setPoll(0);setPaused(false);setRetry(n=>n+1);};
  const suspended=paused||!!error||loading||poll>=29;
  return <section className="worker-sessions" aria-labelledby="worker-sessions-title">
    <h2 id="worker-sessions-title">Rejestr wykonawców</h2>
    <p>Sygnały procesów są zapisywane także podczas oczekiwania na zadania. Status dotyczy kontaktu z procesem; wyniki analiz i przebiegi pracy są dostępne w kolejkach. Wykonawcy w tym rejestrze nie oznaczają uruchomionych modeli LLM.</p>
    <label htmlFor="worker-kind">Rodzaj wykonawcy</label><select id="worker-kind" value={navigation.kind} onChange={event=>{setLoading(true);setPoll(0);setNavigation({kind:event.target.value as WorkerFilter,cursors:['']});}}><option value="">Wszystkie rodzaje</option><option value="sec_import">Import i analiza SEC</option><option value="document_validation">Weryfikacja dokumentów</option><option value="sec_scheduler">Scheduler SEC</option></select>
    <div><button disabled={loading} onClick={refresh}>Odśwież wykonawców</button><button disabled={loading} onClick={()=>{if(paused||poll>=29)refresh();else setPaused(true);}}>{paused||poll>=29?'Wznów podgląd':'Wstrzymaj podgląd'}</button></div>
    {loading&&<p role="status">Odczyt rejestru wykonawców…</p>}{error&&<p role="alert">{error} Automatyczny podgląd zatrzymany.</p>}
    {(paused||poll>=29)&&<p role="status">{paused?'Podgląd wstrzymany.':'Podgląd zatrzymany po 30 odczytach.'} Aktualna aktywność procesów wymaga nowego odczytu.</p>}
    {snapshot&&<p>Obserwacja serwera: {time(snapshot.page.observed_at)}. Brak nowego sygnału przez 45 sekund oznacza utratę kontaktu. Zakończenie sesji opisuje proces, a nie powodzenie zadania.</p>}
    {snapshot?.page.items.length===0&&<p>Brak sesji wykonawców na tej stronie.</p>}
    {snapshot&&snapshot.page.items.length>0&&<div className="task-table"><table><thead><tr><th>Wykonawca</th><th>Kontakt i sesja</th><th>Czas pracy</th><th>Szczegóły</th></tr></thead><tbody>{snapshot.page.items.map(item=>{
      const status=observedWorkerStatus(item,clock-snapshot.requestedAt,suspended);
      return <tr key={item.session_id}><th scope="row">{item.worker_id}<small>{workerKinds[item.kind]}</small><small>PID {item.process_id} · {item.mode==='once'?'Jednorazowy przebieg':'Praca ciągła'}</small></th>
        <td><span className={"badge worker-status worker-status-"+status}>{workerStatuses[status]}</span>{status==='unknown'&&<small>Ostatnia obserwacja: {workerStatuses[item.status]}</small>}<small>Ostatni sygnał: {time(item.heartbeat_at)}</small><small>Ważność kontaktu do {time(item.contact_expires_at)}</small></td>
        <td><small>Start {time(item.started_at)}</small><small>Koniec {time(item.stopped_at)}</small>{item.stop_reason&&<small>{workerStopReasons[item.stop_reason]}</small>}{item.error_code&&<small>Kod: {item.error_code}</small>}</td>
        <td><details><summary>Dane sesji</summary><p>Sesja <code>{item.session_id}</code></p><p>Implementacja <code>{item.implementation_sha256}</code></p><p>Stan odczytany {time(item.observed_at)}</p></details></td>
      </tr>;
    })}</tbody></table></div>}
    {(navigation.cursors.length>1||snapshot?.page.next_after_id)&&<nav aria-label="Strony sesji wykonawców"><button disabled={loading||navigation.cursors.length===1} onClick={()=>{setLoading(true);setPoll(0);setNavigation(value=>({...value,cursors:value.cursors.slice(0,-1)}));}}>← Wstecz</button><button disabled={loading||!snapshot?.page.next_after_id} onClick={()=>{const next=snapshot?.page.next_after_id;if(next){setLoading(true);setPoll(0);setNavigation(value=>({...value,cursors:[...value.cursors,next]}));}}}>Dalej →</button></nav>}
  </section>;
}

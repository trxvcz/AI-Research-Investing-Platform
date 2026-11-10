import {useEffect, useRef, useState} from 'react';
import {QueueDocumentTask} from './document-tasks';
import {assertArchiveIdentity, assertReviewIdentity, bytesToBase64, checkChronology, explicitTimestamp, latestReviews, MAX_DOCUMENT_BYTES, MAX_DRAFT_BYTES, requireFileSize, selectImportAttempt} from './document-archive-state';
import type {ArchiveCreate, ArchivePage, ArchiveRecord, ReviewCommand, ReviewEvent} from './document-archive-state';

const base='/v1/panel/documents';
const requestHeaders={'Content-Type':'application/json','X-Alphasense-Panel':'1',Accept:'application/json'};
const statuses={blocked:'Zablokowany',rejected:'Odrzucony przez walidator',needs_review:'Do przeglądu'};
const verdicts={accepted:'Zaakceptowany w przeglądzie',rejected:'Odrzucony w przeglądzie'};
const scopeLabels={consolidated:'Skonsolidowane',separate:'Jednostkowe',unknown:'Zakres nieustalony'};
const time=(value:string)=>new Intl.DateTimeFormat('pl-PL',{dateStyle:'medium',timeStyle:'medium',timeZone:'UTC'}).format(new Date(value))+' UTC';

class ArchiveFailure extends Error {
  status:number;
  constructor(status:number,message:string){super(message);this.status=status;}
}
async function readResponse<T>(response:Response):Promise<T>{
  if(!response.ok)throw new ArchiveFailure(response.status,response.status===503?'Archiwum jest chwilowo niedostępne.':response.status===404?'Nie znaleziono dokumentu.':response.status===409?'Stan lub tożsamość zapisu uległy zmianie. Odśwież dane.':response.status===422?'Dane nie spełniają kontraktu archiwum. Sprawdź format, daty i szkic.':response.status===413?'Przekroczono limit rozmiaru importu.':'Nie udało się wykonać operacji ('+response.status+').');
  return await response.json() as T;
}
const errorText=(error:unknown)=>error instanceof ArchiveFailure?error.message:'Nie potwierdzono wyniku operacji. Sprawdź połączenie i ponów tę samą próbę.';

export function DocumentArchive({onTaskQueued}:{onTaskQueued?:()=>void}={}){
  const [cursorStack,setCursorStack]=useState<string[]>(['']);
  const [reload,setReload]=useState(0);
  const [selected,setSelected]=useState('');
  const [page,setPage]=useState<{cursor:string;data:ArchivePage}>();
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(false);
  const cursor=cursorStack[cursorStack.length-1];
  const current=page?.cursor===cursor?page.data:undefined;
  useEffect(()=>{
    const abort=new AbortController();
    const timeout=setTimeout(()=>{setError('Odczyt archiwum trwa zbyt długo. Odśwież listę.');setLoading(false);abort.abort();},30000);
    setLoading(true);setError('');
    const params=new URLSearchParams({limit:'10'});if(cursor)params.set('after_id',cursor);
    fetch(base+'?'+params,{signal:abort.signal,cache:'no-store',headers:{Accept:'application/json'}})
      .then(readResponse<ArchivePage>)
      .then(data=>{if(!abort.signal.aborted)setPage({cursor,data});})
      .catch(failure=>{if(!abort.signal.aborted)setError(errorText(failure));})
      .finally(()=>{clearTimeout(timeout);if(!abort.signal.aborted)setLoading(false);});
    return()=>{clearTimeout(timeout);abort.abort();};
  },[cursor,reload]);
  const open=(id:string)=>{setSelected(id);setReload(n=>n+1);};
  return <section className="document-archive" aria-labelledby="document-archive-title">
    <h2 id="document-archive-title">Szkice z dokumentów</h2>
    <p>Importuj dokument i zapisany szkic JSON, sprawdź cytaty oraz zapisz decyzję. Dokumenty zostają w lokalnym archiwum PostgreSQL. Ten formularz nie wywołuje modelu.</p>
    <ImportDocument onImported={open}/>
    <h3>Zapisane dokumenty</h3>
    <button disabled={loading} onClick={()=>setReload(n=>n+1)}>Odśwież archiwum</button>
    {loading&&<p role="status">Wczytywanie archiwum…</p>}
    {error&&<p role="alert">{error}</p>}
    {current?.items.length===0&&<p>Nie zapisano jeszcze dokumentów na tej stronie.</p>}
    {current&&current.items.length>0&&<ul>{current.items.map(item=><li key={item.archive_id}>
      <button aria-pressed={selected===item.archive_id} onClick={()=>open(item.archive_id)}>{item.title}</button>
      <span> · Walidacja: {statuses[item.validation_status]} · {item.fact_count} faktów · rewizja przeglądu {item.review_revision}</span>
      <small> Zapisano {time(item.created_at)}</small>
    </li>)}</ul>}
    {(cursorStack.length>1||current?.next_after_id)&&<nav aria-label="Strony dokumentów">
      <button disabled={loading||cursorStack.length===1} onClick={()=>setCursorStack(values=>values.slice(0,-1))}>← Wstecz</button>
      <button disabled={loading||!current?.next_after_id} onClick={()=>{if(current?.next_after_id)setCursorStack(values=>[...values,current.next_after_id!]);}}>Dalej →</button>
    </nav>}
    {selected&&<DocumentDetails key={selected} archiveId={selected} reload={reload} onChanged={()=>setReload(n=>n+1)} onTaskQueued={onTaskQueued}/>}
  </section>;
}

function ImportDocument({onImported}:{onImported:(id:string)=>void}){
  const [title,setTitle]=useState('');
  const [format,setFormat]=useState<ArchiveCreate['format']>('text');
  const [classification,setClassification]=useState<ArchiveCreate['classification']>('private');
  const [document,setDocument]=useState<File>();
  const [draft,setDraft]=useState<File>();
  const [available,setAvailable]=useState('');
  const [asOf,setAsOf]=useState(()=>new Date().toISOString());
  const [provider,setProvider]=useState('offline-import');
  const [model,setModel]=useState('');
  const [prompt,setPrompt]=useState('');
  const [pending,setPending]=useState<ArchiveCreate>();
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [success,setSuccess]=useState('');
  const lock=useRef(false);
  const mounted=useRef(true);
  const controller=useRef<AbortController|undefined>(undefined);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;controller.current?.abort();};},[]);
  const send=async(attempt:ArchiveCreate)=>{
    const abort=new AbortController();controller.current=abort;
    const timeout=setTimeout(()=>abort.abort(),30000);
    try{
      const record=await fetch(base,{method:'POST',headers:requestHeaders,body:JSON.stringify(attempt),signal:abort.signal}).then(readResponse<ArchiveRecord>);
      assertArchiveIdentity(record,attempt.archive_id);
      if(mounted.current){setPending(undefined);setSuccess('Zapisano dokument i szkic. Sprawdź fakty poniżej.');onImported(record.archive_id);}
    }catch(failure){
      if(mounted.current){
        setError(errorText(failure));
        if(failure instanceof ArchiveFailure&&[400,403,413,422].includes(failure.status))setPending(undefined);
      }
    }finally{clearTimeout(timeout);if(mounted.current){lock.current=false;setBusy(false);}}
  };
  const submit=async()=>{
    if(lock.current)return;lock.current=true;setBusy(true);setError('');setSuccess('');
    try{
      if(pending){await send(pending);return;}
      if(!document||!draft)throw Error('Wybierz dokument oraz zapisany szkic JSON.');
      if(!title.trim())throw Error('Podaj tytuł dokumentu.');
      requireFileSize(document.size,MAX_DOCUMENT_BYTES);requireFileSize(draft.size,MAX_DRAFT_BYTES);
      const source_available_at=explicitTimestamp(available),as_of=explicitTimestamp(asOf);
      checkChronology(source_available_at,as_of);
      const [bytes,draftBytes]=await Promise.all([document.arrayBuffer(),draft.arrayBuffer()]);
      const draft_json=new TextDecoder('utf-8',{fatal:true}).decode(draftBytes);
      if(!draft_json.trim())throw Error('Szkic JSON jest pusty.');
      const attempt=selectImportAttempt({title:title.trim(),instrument_id:null,format,classification,content_base64:bytesToBase64(new Uint8Array(bytes)),draft_json,provider_id:provider.trim()||'offline-import',model_id:model.trim()||null,prompt_version:prompt.trim()||null,source_available_at,as_of},undefined,()=>crypto.randomUUID());
      if(!mounted.current)return;
      setPending(attempt);await send(attempt);
    }catch(failure){if(mounted.current){setError(failure instanceof Error?failure.message:'Nie można odczytać plików.');setBusy(false);lock.current=false;}}
  };
  return <details><summary>Dodaj dokument i szkic</summary>
    <p>Dokument: maks. 1 MiB; szkic JSON UTF-8: maks. 256 KiB. Obsługiwane formaty to tekst, statyczny HTML i XLSX bez formuł. PDF/OCR nie jest jeszcze obsługiwany.</p>
    <form onSubmit={event=>{event.preventDefault();void submit();}}>
      <fieldset disabled={busy||!!pending}>
        <legend>Import lokalny</legend>
        <label htmlFor="document-title">Tytuł</label><input id="document-title" required maxLength={128} value={title} onChange={event=>setTitle(event.target.value)}/>
        <label htmlFor="document-file">Dokument źródłowy</label><input id="document-file" type="file" accept=".txt,.text,.html,.htm,.xlsx" required onChange={event=>{const file=event.target.files?.[0];setDocument(file);if(file&&!title)setTitle(file.name.slice(0,128));}}/>
        <label htmlFor="document-format">Format dokumentu</label><select id="document-format" value={format} onChange={event=>setFormat(event.target.value as ArchiveCreate['format'])}><option value="text">Tekst UTF-8</option><option value="html">Statyczny HTML</option><option value="xlsx">XLSX</option></select>
        <label htmlFor="document-draft">Zapisany szkic JSON</label><input id="document-draft" type="file" accept=".json,application/json" required onChange={event=>setDraft(event.target.files?.[0])}/>
        <label htmlFor="document-classification">Klasyfikacja dokumentu</label><select id="document-classification" value={classification} onChange={event=>setClassification(event.target.value as ArchiveCreate['classification'])}><option value="private">Prywatny</option><option value="public">Publiczny</option><option value="secret">Tajny</option></select>
        <p>W każdej klasyfikacji import pozostaje lokalny. Zmiana na „Publiczny” nie uruchamia wysyłki do dostawcy.</p>
        <label htmlFor="document-available">Dostępny od — data ze strefą</label><input id="document-available" required value={available} placeholder="2026-11-10T12:00:00+01:00" onChange={event=>setAvailable(event.target.value)}/>
        <label htmlFor="document-asof">Stan analizy na — data ze strefą</label><input id="document-asof" required value={asOf} onChange={event=>setAsOf(event.target.value)}/>
        <p>Podaj pełną datę z sekundami i jawną strefą, np. +01:00 albo Z (UTC). Data dostępności nie może być późniejsza od stanu analizy.</p>
        <details><summary>Deklarowane pochodzenie szkicu</summary>
          <p>Te pola są opisem podanym przy imporcie. Nie potwierdzają rzeczywistego wywołania dostawcy.</p>
          <label htmlFor="document-provider">Dostawca lub tryb</label><input id="document-provider" maxLength={128} value={provider} onChange={event=>setProvider(event.target.value)}/>
          <label htmlFor="document-model">Model — opcjonalnie</label><input id="document-model" maxLength={128} value={model} onChange={event=>setModel(event.target.value)}/>
          <label htmlFor="document-prompt">Wersja promptu — opcjonalnie</label><input id="document-prompt" maxLength={128} value={prompt} onChange={event=>setPrompt(event.target.value)}/>
        </details>
      </fieldset>
      {!pending&&<button disabled={busy}>{busy?'Zapisywanie…':'Zapisz dokument i szkic'}</button>}
      {pending&&<><p>Próba {pending.archive_id}. Ponowienie zachowuje dokładnie ten sam dokument, szkic i identyfikator.</p><button disabled={busy}>{busy?'Sprawdzanie zapisu…':'Ponów tę samą próbę'}</button><button type="button" disabled={busy} onClick={()=>{onImported(pending.archive_id);}}>Sprawdź dokument w archiwum</button><button type="button" disabled={busy} onClick={()=>{setPending(undefined);setError('');}}>Rozpocznij osobny import</button><p>Osobny import otrzyma nowy identyfikator. Poprzedni zapis może już istnieć w archiwum.</p></>}
    </form>
    {error&&<p role="alert">{error}</p>}{success&&<p role="status">{success}</p>}
  </details>;
}

function DocumentDetails({archiveId,reload,onChanged,onTaskQueued}:{archiveId:string;reload:number;onChanged:()=>void;onTaskQueued?:()=>void}){
  const [record,setRecord]=useState<ArchiveRecord>();
  const [error,setError]=useState('');
  const [loading,setLoading]=useState(false);
  useEffect(()=>{
    const abort=new AbortController();
    const timeout=setTimeout(()=>{setError('Odczyt dokumentu trwa zbyt długo. Odśwież archiwum.');setLoading(false);abort.abort();},30000);
    setLoading(true);setError('');setRecord(undefined);
    fetch(base+'/'+encodeURIComponent(archiveId),{signal:abort.signal,cache:'no-store',headers:{Accept:'application/json'}})
      .then(readResponse<ArchiveRecord>).then(value=>{assertArchiveIdentity(value,archiveId);if(!abort.signal.aborted)setRecord(value);})
      .catch(failure=>{if(!abort.signal.aborted)setError(errorText(failure));})
      .finally(()=>{clearTimeout(timeout);if(!abort.signal.aborted)setLoading(false);});
    return()=>{clearTimeout(timeout);abort.abort();};
  },[archiveId,reload]);
  if(loading)return <p role="status">Wczytywanie dokumentu i historii…</p>;
  if(error)return <div role="alert"><p>{error}</p><button onClick={onChanged}>Odśwież dokument</button></div>;
  if(!record)return null;
  const latest=latestReviews(record.reviews);
  return <article aria-labelledby="selected-document-title">
    <h3 id="selected-document-title">{record.title}</h3>
    <p>Walidacja szkicu: {statuses[record.validation_status]} · {record.format} · {record.classification} · rewizja przeglądu {record.review_revision}</p>
    <p>Import z niezweryfikowanym pochodzeniem. Deklarowany dostawca: {record.provider_id}; model: {record.model_id??'nie podano'}; prompt: {record.prompt_version??'nie podano'}.</p>
    <p>Dostępny od {time(record.source_available_at)}. Stan analizy na {time(record.as_of)}. Zapisano {time(record.created_at)}.</p>
    <details><summary>Tożsamość i sumy kontrolne</summary><p>Archiwum: <code>{record.archive_id}</code></p><p>SHA-256 dokumentu: <code>{record.document_sha256}</code></p><p>SHA-256 szkicu: <code>{record.draft_sha256}</code></p></details>
    <a download href={base+'/'+encodeURIComponent(archiveId)+'/content'}>Pobierz oryginalny dokument</a>
    <QueueDocumentTask archiveId={archiveId} onQueued={onTaskQueued}/>
    <p className="disclaimer">Akceptacja w przeglądzie zapisuje decyzję człowieka. Nie publikuje danych w raporcie i nie tworzy rekomendacji inwestycyjnej.</p>
    {record.result.error_code&&<p>Walidator: {record.result.error_code}</p>}
    {record.result.facts.length===0&&<p>Szkic nie zawiera faktów dostępnych do przeglądu.</p>}
    {record.result.facts.map((review,index)=>{const fact=review.fact;const decision=latest.get(index);return <section key={index} aria-label={'Fakt '+(index+1)}>
      <h4>{index+1}. {fact.metric}: <strong>{fact.value} {fact.currency}</strong></h4>
      <p>Okres {fact.period_start} — {fact.period_end} · {scopeLabels[fact.scope]}</p>
      <p>Oryginalny zapis liczby: {fact.value_token}; mnożnik: {fact.scale}. {statuses[review.status]} ({review.reason_code}).</p>
      {fact.evidence.map((evidence,evidenceIndex)=>{const block=record.packet.blocks.find(item=>item.block_id===evidence.block_id);return <div key={evidenceIndex}>
        <blockquote>{evidence.quote}</blockquote><small>Blok {evidence.block_id}{block?' · '+block.locator:''}</small>
        {block&&<details><summary>Kontekst cytatu</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{block.text}</pre></details>}
      </div>;})}
      <p>{decision?verdicts[decision.command.verdict]+' · rewizja '+decision.revision:'Brak decyzji recenzenta'}</p>
    </section>;})}
    {record.result.facts.length>0&&<ReviewDocument key={record.review_revision} record={record} onChanged={onChanged}/>}
    <details><summary>Historia decyzji ({record.reviews.length})</summary>{record.reviews.length===0?<p>Historia jest pusta.</p>:<ol>{record.reviews.map(event=><li key={event.revision}>Rewizja {event.revision} · fakt {event.command.fact_index+1} · {verdicts[event.command.verdict]} · {time(event.reviewed_at)}<p>{event.command.note}</p></li>)}</ol>}</details>
    <details><summary>Oryginalny szkic JSON</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{record.draft_json}</pre></details>
  </article>;
}

function ReviewDocument({record,onChanged}:{record:ArchiveRecord;onChanged:()=>void}){
  const [factIndex,setFactIndex]=useState(0);
  const [verdict,setVerdict]=useState<ReviewCommand['verdict']>('rejected');
  const [note,setNote]=useState('');
  const [pending,setPending]=useState<ReviewCommand>();
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const lock=useRef(false);
  const mounted=useRef(true);
  const controller=useRef<AbortController|undefined>(undefined);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;controller.current?.abort();};},[]);
  const canAccept=record.result.facts[factIndex]?.status==='needs_review';
  const submit=async()=>{
    if(lock.current)return;
    if(!pending&&(!note.trim()||(verdict==='accepted'&&!canAccept)))return;
    lock.current=true;setBusy(true);setError('');
    const command=pending??{command_id:crypto.randomUUID(),expected_revision:record.review_revision,fact_index:factIndex,verdict,note:note.trim()};
    setPending(command);
    const abort=new AbortController();controller.current=abort;const timeout=setTimeout(()=>abort.abort(),30000);
    try{
      const event=await fetch(base+'/'+encodeURIComponent(record.archive_id)+'/reviews',{method:'POST',headers:requestHeaders,body:JSON.stringify(command),signal:abort.signal}).then(readResponse<ReviewEvent>);
      assertReviewIdentity(event,command);
      if(mounted.current){setPending(undefined);setNote('');onChanged();}
    }catch(failure){if(mounted.current){
      setError(errorText(failure));
      if(failure instanceof ArchiveFailure&&failure.status===409){setPending(undefined);setError('Historia zmieniła się. Odśwież dokument i sprawdź decyzje przed ponownym zapisem.');}
      else if(failure instanceof ArchiveFailure&&[400,403,413,422].includes(failure.status))setPending(undefined);
    }}finally{clearTimeout(timeout);if(mounted.current){lock.current=false;setBusy(false);}}
  };
  return <form onSubmit={event=>{event.preventDefault();void submit();}}>
    <fieldset disabled={busy||!!pending||record.review_revision>=10000}><legend>Zapisz decyzję recenzenta</legend>
      <label htmlFor="review-fact">Fakt</label><select id="review-fact" value={factIndex} onChange={event=>{setFactIndex(Number(event.target.value));setVerdict('rejected');setError('');}}>{record.result.facts.map((item,index)=><option key={index} value={index}>{index+1}. {item.fact.metric} · {item.fact.value} {item.fact.currency}</option>)}</select>
      <label htmlFor="review-verdict">Decyzja</label><select id="review-verdict" value={verdict} onChange={event=>setVerdict(event.target.value as ReviewCommand['verdict'])}><option value="rejected">Odrzuć</option><option disabled={!canAccept} value="accepted">Zaakceptuj w przeglądzie</option></select>
      {!canAccept&&<p>Walidator odrzucił ten fakt. Nie można go zaakceptować.</p>}
      <label htmlFor="review-note">Uzasadnienie</label><textarea id="review-note" required maxLength={1000} value={note} onChange={event=>setNote(event.target.value)}/>
    </fieldset>
    <button disabled={busy||record.review_revision>=10000||(!pending&&!note.trim())}>{busy?'Zapisywanie decyzji…':pending?'Ponów tę samą decyzję':'Zapisz decyzję'}</button>
    {pending&&<p>Wynik zapisu może być nieznany. Ponowienie zachowuje identyfikator decyzji {pending.command_id}.</p>}
    <button type="button" disabled={busy} onClick={onChanged}>Sprawdź aktualną historię</button>
    {record.review_revision>=10000&&<p>Osiągnięto limit historii przeglądu tego dokumentu.</p>}
    {error&&<p role="alert">{error}</p>}
  </form>;
}

import {useEffect,useRef,useState} from 'react';
import {bytesToBase64,documentReadingOptions,MAX_DOCUMENT_BYTES,requireFileSize} from './document-archive-state';
import type {ArchiveCreate} from './document-archive-state';
import {assertPreviewIdentity,samePreviewSelection} from './document-preview-state';
import type {PreviewCreate,PreviewResult,PreviewSelection} from './document-preview-state';

export function PreviewDocument({file,format,classification,numberLocale}:{file:File|undefined;format:ArchiveCreate['format'];classification:ArchiveCreate['classification'];numberLocale:''|'en-US'}){
  const [stored,setStored]=useState<{result:PreviewResult;selection:PreviewSelection}>();
  const selection={file,format,classification,numberLocale};
  const result=stored&&samePreviewSelection(stored.selection,selection)?stored.result:undefined;
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [visible,setVisible]=useState(20);
  const generation=useRef(0);
  const active=useRef<AbortController|undefined>(undefined);
  const lock=useRef(false);
  useEffect(()=>{
    generation.current++;active.current?.abort();lock.current=false;
    setStored(undefined);setError('');setBusy(false);setVisible(20);
    return()=>{generation.current++;active.current?.abort();lock.current=false;};
  },[file,format,classification,numberLocale]);
  const clear=()=>{generation.current++;active.current?.abort();lock.current=false;setStored(undefined);setError('');setBusy(false);};
  const preview=async()=>{
    if(!file||lock.current)return;
    lock.current=true;const revision=++generation.current;
    const controller=new AbortController();active.current=controller;
    const current=()=>generation.current===revision&&!controller.signal.aborted;
    const timeout=setTimeout(()=>controller.abort(),30000);
    setStored(undefined);setError('');setBusy(true);setVisible(20);
    try{
      requireFileSize(file.size,MAX_DOCUMENT_BYTES);
      const bytes=await file.arrayBuffer();
      if(!current())return;
      const digest=await crypto.subtle.digest('SHA-256',bytes);
      if(!current())return;
      const sha256=Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');
      const options=documentReadingOptions(format,numberLocale);
      const request:PreviewCreate={document_id:crypto.randomUUID(),format,classification,...options,content_base64:bytesToBase64(new Uint8Array(bytes))};
      const response=await fetch('/v1/panel/document-preview',{method:'POST',cache:'no-store',headers:{'Content-Type':'application/json','X-AlphaSense-Panel':'1',Accept:'application/json'},body:JSON.stringify(request),signal:controller.signal});
      if(!response.ok)throw Error(response.status===413?'Przekroczono limit podglądu.':response.status===422?'Nie można odczytać dokumentu z wybranymi ustawieniami. Sprawdź format, rozmiar i ograniczenia czytnika.':'Podgląd dokumentu jest niedostępny.');
      const value:PreviewResult=await response.json();
      assertPreviewIdentity(value,{document_id:request.document_id,format,classification,...options,sha256,byte_length:bytes.byteLength});
      if(current())setStored({result:value,selection});
    }catch(failure){
      if(generation.current===revision)setError(controller.signal.aborted?'Podgląd przerwany lub przekroczono czas oczekiwania.':failure instanceof Error?failure.message:'Nie udało się odczytać dokumentu.');
    }finally{
      clearTimeout(timeout);
      if(generation.current===revision){lock.current=false;setBusy(false);}
    }
  };
  return <section aria-label="Podgląd dokumentu przed importem">
    <p>Najpierw wybierz plik i jego format poniżej. Podgląd działa bez szkicu JSON, nie zapisuje dokumentu do archiwum i nie uruchamia modelu.</p>
    <button type="button" disabled={!file||busy} onClick={()=>void preview()}>{busy?'Odczytywanie dokumentu…':'Podejrzyj dokument bez szkicu'}</button>
    {(busy||result)&&<button type="button" onClick={clear}>Wyczyść podgląd</button>}
    {error&&<p role="alert">{error}</p>}
    {result&&<div>
      <p>Odczytano {result.packet.blocks.length} bloków z {result.byte_length} bajtów. Format: {result.packet.format}; klasyfikacja: {result.packet.classification}. Nie zapisano do archiwum; model nie został wywołany.</p>
      <p>SHA-256: <code>{result.packet.sha256}</code></p>
      {result.packet.format==='html'&&<p>Odczyt: {result.packet.reader_version??'wcześniejsza wersja'}; zapis liczb: {result.packet.number_locale??'niezadeklarowany'}.</p>}
      <p>Tekst źródła jest niezaufany. Lokalizatory służą cytowaniu; sprawdź układ tabel i znaczenie liczb w oryginale.</p>
      {result.packet.blocks.slice(0,visible).map(block=><details key={block.block_id}><summary>{block.block_id} · {block.locator}</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{block.text}</pre></details>)}
      {visible<result.packet.blocks.length&&<button type="button" onClick={()=>setVisible(value=>value+20)}>Pokaż kolejne bloki</button>}
    </div>}
  </section>;
}

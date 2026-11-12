/** Imports are claims, never proof of a model invocation. Types come from the API. */
import type {components} from './schema';
type Model=components['schemas'];
export type ArchiveCreate=Required<Omit<Model['DocumentArchiveCreate'],'reader_version'|'number_locale'>>&Pick<Model['DocumentArchiveCreate'],'reader_version'|'number_locale'>;
export type ReviewCommand=Model['DocumentReviewCommand'];
export type ReviewEvent=Model['DocumentReviewEvent'];
export type ArchiveRecord=Model['DocumentArchiveRecord'];
export type ArchivePage=Model['DocumentArchivePage'];

export const MAX_DOCUMENT_BYTES = 1048576;
export const MAX_DRAFT_BYTES = 262144;

export function requireFileSize(size:number, limit:number):void {
  if (!Number.isInteger(size) || size < 1 || size > limit) throw Error('Plik jest pusty lub przekracza dopuszczalny rozmiar.');
}

export function bytesToBase64(bytes:Uint8Array):string {
  requireFileSize(bytes.byteLength,MAX_DOCUMENT_BYTES);
  let binary='';
  for(let i=0;i<bytes.length;i+=8192) binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
  return btoa(binary);
}

/** Explicit offset avoids guessing the user's timezone or a DST transition. */
export function explicitTimestamp(raw:string):string {
  const value=raw.trim();
  const pattern=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-](\d{2}):(\d{2}))$/;
  const match=pattern.exec(value);
  if(!match)throw Error('Podaj datę z sekundami i strefą, np. 2026-11-10T12:00:00+01:00.');
  const year=Number(match[1]),month=Number(match[2]),day=Number(match[3]);
  const days=new Date(Date.UTC(year,month,0)).getUTCDate();
  if(year<1||month<1||month>12||day<1||day>days||Number(match[4])>23||Number(match[5])>59||Number(match[6])>59
    ||(match[8]!=='Z'&&(Number(match[9])>23||Number(match[10])>59))||!Number.isFinite(Date.parse(value))) {
    throw Error('Data lub strefa czasowa jest nieprawidłowa.');
  }
  // Preserve up to six fractional digits; Date conversion would silently truncate them.
  return value;
}

export function checkChronology(available:string, asOf:string):void {
  // Compare instants at microsecond precision, matching the backend contract.
  const instant=(value:string):bigint=>{
    explicitTimestamp(value);
    const fraction=/\.(\d{1,6})(?:Z|[+-]\d{2}:\d{2})$/.exec(value)?.[1]??'';
    return BigInt(Date.parse(value))*1000n+BigInt(fraction.padEnd(6,'0').slice(3));
  };
  if(instant(available)>instant(asOf))throw Error('Dokument nie mógł być dostępny po dacie stanu analizy.');
}

export function latestReviews(events:ReviewEvent[]):Map<number,ReviewEvent> {
  const result=new Map<number,ReviewEvent>();
  for(const event of events) {
    const previous=result.get(event.command.fact_index);
    if(!previous||previous.revision<event.revision)result.set(event.command.fact_index,event);
  }
  return result;
}

export function assertArchiveIdentity(record:Pick<ArchiveRecord,'archive_id'|'packet'|'result'|'reader_version'|'number_locale'>, id:string):void {
  if(record.archive_id!==id||record.packet.document_id!==id||record.result.document_id!==id
    ||(record.reader_version??null)!==(record.packet.reader_version??null)
    ||(record.number_locale??null)!==(record.packet.number_locale??null)) {
    throw Error('Otrzymany dokument ma inną tożsamość. Odśwież archiwum.');
  }
}

export function documentReadingOptions(format:ArchiveCreate['format'],locale:''|'en-US'):Pick<ArchiveCreate,'reader_version'|'number_locale'> {
  if(locale!==''&&locale!=='en-US')throw Error('Nieobsługiwany zapis liczb.');
  return format==='html'?{reader_version:'table-text-v2',...(locale?{number_locale:locale}:{})}:{};
}

/** A retry must keep both the UUID and the exact immutable request. */
export function selectImportAttempt(payload:Omit<ArchiveCreate,'archive_id'>, previous:ArchiveCreate|undefined, uuid:()=>string):ArchiveCreate {
  if(previous) {
    const {archive_id:_,...saved}=previous;
    if(JSON.stringify(saved)!==JSON.stringify(payload))throw Error('Najpierw rozstrzygnij wynik poprzedniego importu.');
    return previous;
  }
  return {archive_id:uuid(),...payload};
}

export function assertReviewIdentity(event:ReviewEvent, command:ReviewCommand):void {
  if(event.revision!==command.expected_revision+1||JSON.stringify(event.command)!==JSON.stringify(command)) {
    // Property ordering is not an identity requirement in JSON.
    if(event.revision!==command.expected_revision+1||Object.keys(command).some(key=>event.command[key as keyof ReviewCommand]!==command[key as keyof ReviewCommand])) {
      throw Error('Odpowiedź nie odpowiada wysłanej decyzji. Odśwież historię.');
    }
  }
}

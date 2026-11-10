import type {components} from './schema';

type Model=components['schemas'];
export type WorkerSession=Model['WorkerSessionRecord'];
export type WorkerSessionPage=Model['WorkerSessionPage'];
export type WorkerFilter=''|'sec_import'|'document_validation'|'sec_scheduler';
export type ObservedWorkerStatus='online'|'stale'|'stopped'|'unknown';

export const workerKinds={sec_import:'Import i analiza SEC',document_validation:'Weryfikacja dokumentów',sec_scheduler:'Scheduler SEC'};
export const workerStatuses={online:'Sygnał aktualny',stale:'Utrata kontaktu',stopped:'Proces zakończony',unknown:'Stan nieaktualny'};
export const workerStopReasons={completed:'Zakończenie pracy procesu',interrupted:'Przerwanie procesu',error:'Błąd procesu'};

export function workerPageIdentity(kind:WorkerFilter,cursor:string):string {
  return JSON.stringify([kind,cursor]);
}

export function assertWorkerPage(page:WorkerSessionPage,kind:WorkerFilter):void {
  if(page.stale_after_seconds!==45||!Number.isFinite(Date.parse(page.observed_at)))throw Error('Nieprawidłowy czas obserwacji wykonawców.');
  const ids=new Set<string>();
  for(const item of page.items){
    if(ids.has(item.session_id)||item.observed_at!==page.observed_at||(kind&&item.kind!==kind))throw Error('Odpowiedź nie odpowiada wybranej stronie wykonawców.');
    ids.add(item.session_id);
    const observed=Date.parse(item.observed_at),heartbeat=Date.parse(item.heartbeat_at),expires=Date.parse(item.contact_expires_at),started=Date.parse(item.started_at);
    if(![observed,heartbeat,expires,started].every(Number.isFinite)||heartbeat<started||heartbeat>observed||expires-heartbeat!==45000)throw Error('Niespójna chronologia sygnałów wykonawcy.');
    const stopped=item.stopped_at===null?null:Date.parse(item.stopped_at);
    const expected=stopped!==null?'stopped':observed>=expires?'stale':'online';
    if(item.status!==expected||(stopped!==null&&(!Number.isFinite(stopped)||stopped<heartbeat||stopped>observed))||(item.stopped_at===null)!==(item.stop_reason===null))throw Error('Niespójny stan sesji wykonawcy.');
  }
}

/** Elapsed time is monotonic browser time since the request began, not wall time.
 * Including transit time conservatively expires a slow response earlier.
 */
export function observedWorkerStatus(session:Pick<WorkerSession,'status'|'contact_expires_at'|'observed_at'>,elapsedMs:number,suspended:boolean):ObservedWorkerStatus {
  if(session.status==='stopped'||session.status==='stale')return session.status;
  if(session.status!=='online'||suspended||!Number.isFinite(elapsedMs)||elapsedMs<0)return 'unknown';
  const remaining=Date.parse(session.contact_expires_at)-Date.parse(session.observed_at);
  return Number.isFinite(remaining)&&elapsedMs<remaining?'online':'unknown';
}

export function shouldPollWorkerSessions(readIndex:number,error:string,paused:boolean):boolean {
  // Read index zero is the initial request; at most 29 automatic follow-ups.
  return !paused&&!error&&Number.isInteger(readIndex)&&readIndex>=0&&readIndex<29;
}

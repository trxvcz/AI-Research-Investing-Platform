import type {components} from './schema';
type Model=components['schemas'];
export type ScheduleCreate=Required<Model['ScheduleCreate']>;
export type ScheduleCommand=Model['ScheduleCommand'];
export type ScheduleRecord=Model['ScheduleRecord'];
export type SchedulePage=Model['SchedulePage'];
export type OccurrencePage=Model['ScheduleOccurrencePage'];
export type TaskEventPage=Model['ImportTaskEventPage'];

const instant=(value:string):bigint=>{
  const stamp=Date.parse(value);
  if(!Number.isFinite(stamp))throw Error('Nieprawidłowa data w odpowiedzi.');
  const fraction=/\.(\d{1,6})(?:Z|[+-]\d{2}:\d{2})$/.exec(value)?.[1]??'';
  return BigInt(stamp)*1000n+BigInt(fraction.padEnd(6,'0').slice(3));
};
export function hoursToInterval(raw:string):number {
  const hours=Number(raw);
  if(!raw.trim()||!Number.isInteger(hours)||hours<1||hours>720)throw Error('Odstęp musi wynosić od 1 do 720 pełnych godzin.');
  return hours*3600;
}
export function scheduleAttempt(payload:Omit<ScheduleCreate,'schedule_id'>,previous:ScheduleCreate|undefined,uuid:()=>string):ScheduleCreate {
  if(previous){const {schedule_id:_,...saved}=previous;if(JSON.stringify(saved)!==JSON.stringify(payload))throw Error('Najpierw rozstrzygnij poprzedni zapis.');return previous;}
  return {schedule_id:uuid(),...payload};
}
export function assertScheduleCreated(record:ScheduleRecord,attempt:ScheduleCreate):void {
  if(record.schedule_id!==attempt.schedule_id||record.template.symbol!==attempt.symbol.trim().toUpperCase()||(attempt.exchange_mic!==null&&record.template.exchange_mic!==attempt.exchange_mic)||record.interval_seconds!==attempt.interval_seconds||instant(record.first_run_at)!==instant(attempt.first_run_at)||record.template.refresh!==attempt.refresh)throw Error('Odpowiedź nie odpowiada zapisanemu harmonogramowi.');
}
export function assertScheduleCommand(record:ScheduleRecord,id:string,command:ScheduleCommand):void {
  if(record.schedule_id!==id||!Number.isInteger(record.revision)||typeof record.enabled!=='boolean'||record.revision<command.expected_revision+1||(record.revision===command.expected_revision+1&&record.enabled!==command.enabled))throw Error('Nie potwierdzono tożsamości zmiany harmonogramu.');
}
export function assertOccurrences(page:OccurrencePage,id:string,after:number):void {
  if(page.schedule_id!==id)throw Error('Historia dotyczy innego harmonogramu.');
  let sequence=after;
  for(const event of page.items){
    if(event.schedule_id!==id||event.sequence!==++sequence||!['enqueued','skipped_busy'].includes(event.outcome)||!Number.isInteger(event.skipped_slots)||event.skipped_slots<0||((event.outcome==='enqueued')!==(event.run_id!==null))||instant(event.dispatched_at)<instant(event.scheduled_for))throw Error('Niespójna historia uruchomień harmonogramu.');
  }
  if(page.next_after_sequence!==null&&page.next_after_sequence!==sequence)throw Error('Niespójny kursor historii.');
}
export function assertTaskEvents(page:TaskEventPage,id:string,after:number):void {
  if(page.run_id!==id||!['complete','legacy_snapshot'].includes(page.coverage))throw Error('Historia dotyczy innego zadania.');
  let sequence=after;
  for(const event of page.items){
    if(event.run_id!==id||event.task.run_id!==id||!['created','transition','legacy_snapshot'].includes(event.kind)||event.sequence!==++sequence)throw Error('Niespójna historia etapów zadania.');
  }
  if(page.next_after_sequence!==null&&page.next_after_sequence!==sequence)throw Error('Niespójny kursor etapów.');
}
export function scheduleReadIdentity(retry:number,poll:number):string{return `${retry}:${poll}`;}
export function shouldPollSchedules(enabled:boolean,readIndex:number,error:string):boolean{return enabled&&!error&&Number.isInteger(readIndex)&&readIndex>=0&&readIndex<29;}

import type {components} from './schema';

type Model=components['schemas'];
export type DocumentTaskCreate=Required<Model['DocumentTaskCreate']>;
export type DocumentTaskRecord=Model['DocumentTaskRecord'];
export type DocumentTaskPage=Model['DocumentTaskPage'];
export type DocumentTaskDetail=Model['DocumentTaskDetail'];

export const documentTaskStatuses={queued:'Oczekuje',running:'W toku',completed:'Zakończone',blocked:'Zablokowane',failed:'Błąd'};
export const documentTaskStages={queued:'Oczekiwanie',reading:'Odczyt archiwum',validating:'Weryfikacja szkicu',archiving:'Zapis audytu',completed:'Zakończone',blocked:'Zablokowane',failed:'Błąd'};

export function documentTaskRefreshIdentity(retry:number,poll:number,refreshKey:number):string {
  return `${retry}:${poll}:${refreshKey}`;
}

export function documentTaskAttempt(archiveId:string,previous:DocumentTaskCreate|undefined,uuid:()=>string):DocumentTaskCreate {
  if(previous){
    if(previous.archive_id!==archiveId||previous.mode!=='validate_saved_draft')throw Error('Najpierw rozstrzygnij poprzednie zlecenie.');
    return previous;
  }
  return {job_id:uuid(),archive_id:archiveId,mode:'validate_saved_draft'};
}

export function assertDocumentTaskIdentity(task:DocumentTaskRecord,expected:Pick<DocumentTaskCreate,'job_id'|'archive_id'|'mode'>):void {
  if(task.job_id!==expected.job_id||task.archive_id!==expected.archive_id||task.mode!==expected.mode)throw Error('Odpowiedź dotyczy innego zadania lub dokumentu.');
}

export function assertDocumentTaskDetail(detail:DocumentTaskDetail,jobId:string):void {
  if(detail.task.job_id!==jobId)throw Error('Odpowiedź dotyczy innego zadania.');
  if(detail.task.result&&detail.task.result.document_id!==detail.task.archive_id)throw Error('Wynik dotyczy innego dokumentu.');
  for(const audit of detail.audits){
    if(audit.request_sha256!==detail.task.input_sha256||(audit.result&&audit.result.document_id!==detail.task.archive_id))throw Error('Audyt nie odpowiada zamrożonemu wejściu zadania.');
    if(audit.provider_called!==false||audit.cost_usd!=='0'||audit.usage_status!=='not_applicable'||audit.input_tokens!==null||audit.output_tokens!==null||audit.model_id!==null||audit.prompt_version!==null||audit.response_sha256!==null)throw Error('Audyt ma nieobsługiwane dane użycia modelu.');
  }
}

export function shouldPollDocumentTasks(tasks:Pick<DocumentTaskRecord,'status'>[],reads:number,error:string):boolean {
  // Initial read plus at most 29 automatic refreshes: 30 reads per session.
  return !error&&reads<29&&tasks.some(task=>task.status==='queued'||task.status==='running');
}

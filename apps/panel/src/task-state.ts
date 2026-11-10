import type {components} from './schema';

export type Task = components['schemas']['TaskRecord'];
export type TaskPage = components['schemas']['TaskPage'];
export const taskStatuses: Record<Task['status'], string> = {queued:'Oczekuje',running:'W toku',completed:'Zakończone',failed:'Błąd'};
export const taskStages: Record<Task['stage'], string> = {queued:'Kolejka',import:'Przygotowanie danych',analysis:'Analiza i raport',completed:'Zakończone',failed:'Zatrzymane'};
export function completedAnalysis(task: Task): (components['schemas']['PanelAnalysisResult'] & {symbol:string}) | undefined {
  if (task.status !== 'completed' || !task.instrument_id || !task.report_id || !task.revision) return undefined;
  return {run_id:task.run_id, symbol:task.symbol, status:'completed', instrument_id:task.instrument_id,
    report_id:task.report_id, revision:task.revision, error_reason:task.error_reason};
}
export function shouldPollTask(task: Task|undefined, polls: number, error: string): boolean {
  return !!task && (task.status === 'queued' || task.status === 'running') && polls < 60 && !error;
}
export function assertTaskIdentity(task: Task, identity: {run_id:string;symbol:string;exchange_mic?:string|null}): void {
  if(task.run_id!==identity.run_id || task.symbol!==identity.symbol || (identity.exchange_mic != null && task.exchange_mic!==identity.exchange_mic)) throw Error('Odpowiedź dotyczy innego zadania. Sprawdź stan ponownie.');
}

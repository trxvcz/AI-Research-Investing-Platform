export type AiClaim = {text: string; observation_indexes: number[]};
export type AiNarrative = {summary: AiClaim[]; strengths: AiClaim[]; risks: AiClaim[]; questions: AiClaim[]; limitations: string[]};
export type AiAnalysisRecord = {
  request_id: string; report_id: string; revision: number; report_checksum: string;
  status: 'running' | 'completed' | 'failed'; created_at: string; finished_at: string | null;
  model_id: string; prompt_version: 'report-synthesis-v1'|'report-history-v2'; analysis: AiNarrative | AiHistoryNarrative | null; error_code: string | null; reserved_pln: string; evidence_context?:AiHistoryContext|null;
};
export type AiBudget = {budget_pln: string; reserved_pln: string; remaining_pln: string; reservation_per_attempt_pln: string; enabled: boolean; reason: string | null};
export type AiReportIdentity = {report_id: string; revision: number; checksum: string};
export type AiAttempt = {request_id: string; report_id: string; revision: number; report_checksum: string};
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const checksum = /^[a-f0-9]{64}$/;
const isObject = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const boundedText = (value: unknown, max: number): value is string => typeof value === 'string' && value.trim().length > 0 && Array.from(value).length <= max;
const timestamp = (value: unknown): value is string => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const money = (value: unknown): value is string => typeof value === 'string' && /^(?:0|[1-9][0-9]{0,5})\.[0-9]{2}$/.test(value);
const grosz = (value: string) => BigInt(value.replace('.', ''));

export function assertAiBudget(value: unknown): asserts value is AiBudget {
  if (!isObject(value) || !money(value.budget_pln) || !money(value.reserved_pln) || !money(value.remaining_pln) || !money(value.reservation_per_attempt_pln) || typeof value.enabled !== 'boolean' || (value.reason !== null && !boundedText(value.reason, 512))) throw Error('Nieprawidłowy stan limitu AI.');
  if (grosz(value.reserved_pln) + grosz(value.remaining_pln) !== grosz(value.budget_pln) || grosz(value.reservation_per_attempt_pln) <= 0n) throw Error('Niespójny stan limitu AI.');
}

export function canGenerateAi(budget: AiBudget | undefined): boolean {
  return !!budget?.enabled && grosz(budget.remaining_pln) >= grosz(budget.reservation_per_attempt_pln);
}

export function selectAiAttempt(identity: AiReportIdentity, previous: AiAttempt | undefined, newId: () => string): AiAttempt {
  if (previous) {
    if (previous.report_id !== identity.report_id || previous.revision !== identity.revision || previous.report_checksum !== identity.checksum || !uuid.test(previous.request_id)) throw Error('Zlecenie należy do innego raportu.');
    return previous;
  }
  const request_id = newId();
  if (!uuid.test(request_id)) throw Error('Nieprawidłowa tożsamość zlecenia.');
  return {request_id, report_id: identity.report_id, revision: identity.revision, report_checksum: identity.checksum};
}

export function parseAiAttempt(raw: string | null, identity: AiReportIdentity): AiAttempt | undefined {
  try {
    const value: unknown = raw === null ? undefined : JSON.parse(raw);
    if (!isObject(value) || typeof value.request_id !== 'string' || value.report_id !== identity.report_id || value.revision !== identity.revision || value.report_checksum !== identity.checksum) return undefined;
    return selectAiAttempt(identity, value as AiAttempt, () => {throw Error('No new request on recovery');});
  } catch { return undefined; }
}

function assertClaim(value: unknown, availableIndexes: ReadonlySet<number>): asserts value is AiClaim {
  if (!isObject(value) || !boundedText(value.text, 1200) || !Array.isArray(value.observation_indexes) || value.observation_indexes.length < 1 || value.observation_indexes.length > 20 || new Set(value.observation_indexes).size !== value.observation_indexes.length || value.observation_indexes.some(index => !Number.isInteger(index) || !availableIndexes.has(index))) throw Error('Analiza zawiera nieprawidłowe odwołanie do danych.');
}

export function assertAiRecord(value: unknown, identity: AiReportIdentity, availableIndexes: ReadonlySet<number>, requestId?: string): asserts value is AiAnalysisRecord {
  if (!isObject(value) || typeof value.request_id !== 'string' || !uuid.test(value.request_id) || (requestId !== undefined && value.request_id !== requestId) || value.report_id !== identity.report_id || value.revision !== identity.revision || value.report_checksum !== identity.checksum || !checksum.test(identity.checksum)) throw Error('Odpowiedź AI nie należy do wybranej rewizji raportu.');
  if (!['running', 'completed', 'failed'].includes(String(value.status)) || !timestamp(value.created_at) || !boundedText(value.model_id, 128) || !['report-synthesis-v1','report-history-v2'].includes(String(value.prompt_version)) || !money(value.reserved_pln)) throw Error('Nieprawidłowa odpowiedź analizy AI.');
  if(value.prompt_version==='report-history-v2') assertAiHistoryContext(value.evidence_context,identity);
  else if(value.evidence_context!==undefined&&value.evidence_context!==null) throw Error('Starsza analiza nie może zmieniać znaczenia cytowań.');
  if (value.status === 'running') {
    if (value.finished_at !== null || value.analysis !== null || value.error_code !== null) throw Error('Niespójny stan generowania AI.');
    return;
  }
  if (!timestamp(value.finished_at) || Date.parse(value.finished_at) < Date.parse(value.created_at)) throw Error('Nieprawidłowy czas analizy AI.');
  if (value.status === 'failed') {
    if (value.analysis !== null || !boundedText(value.error_code, 128)) throw Error('Niespójny błąd analizy AI.');
    return;
  }
  if (value.error_code !== null || !isObject(value.analysis)) throw Error('Brak treści zakończonej analizy AI.');
  if(value.prompt_version==='report-history-v2') {
    assertAiHistoryNarrative(value.analysis,value.evidence_context as AiHistoryContext);
    return;
  }
  for (const name of ['summary', 'strengths', 'risks', 'questions'] as const) {
    const claims = value.analysis[name];
    if (!Array.isArray(claims) || claims.length > 6 || (name === 'summary' && claims.length === 0)) throw Error('Nieprawidłowa sekcja analizy AI.');
    claims.forEach(claim => assertClaim(claim, availableIndexes));
  }
  if (!Array.isArray(value.analysis.limitations) || value.analysis.limitations.length < 1 || value.analysis.limitations.length > 12 || value.analysis.limitations.some(item => !boundedText(item, 1200))) throw Error('Brak ograniczeń analizy AI.');
}

export function assertAiRecordList(value: unknown, identity: AiReportIdentity, availableIndexes: ReadonlySet<number>): asserts value is AiAnalysisRecord[] {
  if (!Array.isArray(value) || value.length > 20) throw Error('Nieprawidłowe archiwum analiz AI.');
  value.forEach(item => assertAiRecord(item, identity, availableIndexes));
  if (new Set(value.map(item => item.request_id)).size !== value.length) throw Error('Powielona analiza AI w archiwum.');
}
import {assertAiHistoryContext,assertAiHistoryNarrative,verifyAiHistoryContextHash} from './ai-history-context.ts';
import type {AiHistoryContext,AiHistoryNarrative} from './ai-history-context.ts';

/** Network readers must use these wrappers; synchronous assertions check shape, not SHA-256. */
export async function verifyAiRecord(value:unknown,identity:AiReportIdentity,availableIndexes:ReadonlySet<number>,requestId?:string):Promise<AiAnalysisRecord> {
  assertAiRecord(value,identity,availableIndexes,requestId);
  if(value.prompt_version==='report-history-v2') await verifyAiHistoryContextHash(value.evidence_context!);
  return value;
}
export async function verifyAiRecordList(value:unknown,identity:AiReportIdentity,availableIndexes:ReadonlySet<number>):Promise<AiAnalysisRecord[]> {
  assertAiRecordList(value,identity,availableIndexes);
  await Promise.all(value.map(item=>item.prompt_version==='report-history-v2'?verifyAiHistoryContextHash(item.evidence_context!):Promise.resolve()));
  return value;
}

import test from 'node:test';
import assert from 'node:assert/strict';
import {assertAiBudget, assertAiRecord, assertAiRecordList, canGenerateAi, parseAiAttempt, selectAiAttempt} from '../src/ai-analysis-state.ts';

const requestId = '08f94ea4-bb8f-4bb6-9110-fc267dd5cb89';
const report = {report_id:'bd3c4552-1e4d-417b-8279-6a004595e0bb', revision:2, checksum:'a'.repeat(64)};
const available = new Set([0, 2]);
const claim = {text:'Dodatni wynik netto jest mocną stroną raportowanego okresu.', observation_indexes:[2]};
const result = {
  request_id:requestId, report_id:report.report_id, revision:2, report_checksum:report.checksum,
  status:'completed', created_at:'2026-11-11T12:00:00Z', finished_at:'2026-11-11T12:00:05Z',
  model_id:'synthetic-model', prompt_version:'report-synthesis-v1', reserved_pln:'1.00', error_code:null,
  analysis:{summary:[claim], strengths:[claim], risks:[], questions:[], limitations:['Brak danych o wycenie.']},
};
const budget = {budget_pln:'50.00', reserved_pln:'3.00', remaining_pln:'47.00', reservation_per_attempt_pln:'1.00', enabled:true, reason:null};

test('an AI response belongs to an exact report revision and request', () => {
  assert.doesNotThrow(() => assertAiRecord(result, report, available, requestId));
  for (const update of [{report_id:'other'}, {revision:1}, {report_checksum:'b'.repeat(64)}, {request_id:'invalid'}]) {
    assert.throws(() => assertAiRecord({...result, ...update}, report, available, requestId));
  }
  assert.throws(() => assertAiRecord(result, report, available, '17927fca-b046-4819-8d23-9a5c900748d8'));
});

test('AI claims must cite available observations without invented or duplicate references', () => {
  for (const indexes of [[], [1], [-1], [3], [2, 2], ['2'], [NaN]]) {
    const analysis = {...result.analysis, summary:[{...claim, observation_indexes:indexes}]};
    assert.throws(() => assertAiRecord({...result, analysis}, report, available));
  }
  assert.doesNotThrow(() => assertAiRecord({...result, analysis:{...result.analysis, summary:[{...claim, observation_indexes:[0,2]}]}}, report, available));
});

test('completed AI responses require bounded readable conclusions and limitations', () => {
  for (const update of [{summary:[]}, {summary:new Array(7).fill(claim)}, {limitations:[]}, {limitations:['']}, {risks:[{...claim, text:'x'.repeat(1201)}]}, {questions:null}]) {
    assert.throws(() => assertAiRecord({...result, analysis:{...result.analysis, ...update}}, report, available));
  }
  assert.doesNotThrow(() => assertAiRecord({...result, analysis:{...result.analysis, summary:[{...claim, text:'😀'.repeat(1200)}]}}, report, available));
});

test('running and failed states cannot display a fabricated completed narrative', () => {
  const running = {...result, status:'running', finished_at:null, analysis:null};
  assert.doesNotThrow(() => assertAiRecord(running, report, available));
  assert.throws(() => assertAiRecord({...running, analysis:result.analysis}, report, available));
  assert.throws(() => assertAiRecord({...running, finished_at:result.finished_at}, report, available));
  const failed = {...result, status:'failed', analysis:null, error_code:'AI_RESPONSE_INVALID'};
  assert.doesNotThrow(() => assertAiRecord(failed, report, available));
  assert.throws(() => assertAiRecord({...failed, error_code:null}, report, available));
  assert.throws(() => assertAiRecord({...failed, finished_at:'2026-11-11T11:00:00Z'}, report, available));
});

test('AI archive rejects duplicate requests, mixed reports and excessive result pages', () => {
  assert.doesNotThrow(() => assertAiRecordList([result], report, available));
  assert.throws(() => assertAiRecordList([result, result], report, available));
  assert.throws(() => assertAiRecordList([{...result, revision:1}], report, available));
  assert.throws(() => assertAiRecordList(new Array(21).fill(result), report, available));
});

test('ambiguous POST retries retain the exact request identity and never allocate another UUID', () => {
  let created = 0;
  const attempt = selectAiAttempt(report, undefined, () => {created++; return requestId;});
  assert.equal(selectAiAttempt(report, attempt, () => {throw Error('Unexpected new paid request');}), attempt);
  assert.equal(created, 1);
  assert.throws(() => selectAiAttempt({...report, revision:3}, attempt, () => requestId));
  assert.throws(() => selectAiAttempt(report, undefined, () => 'bad-uuid'));
});

test('saved attempts recover only against the same checksum and revision', () => {
  const attempt = selectAiAttempt(report, undefined, () => requestId);
  assert.deepEqual(parseAiAttempt(JSON.stringify(attempt), report), attempt);
  assert.equal(parseAiAttempt(JSON.stringify(attempt), {...report, checksum:'b'.repeat(64)}), undefined);
  assert.equal(parseAiAttempt(JSON.stringify(attempt), {...report, revision:3}), undefined);
  for (const raw of [null, '', 'null', '{}', '{', JSON.stringify({...attempt, request_id:'bad'})]) assert.equal(parseAiAttempt(raw, report), undefined);
});

test('budget requires exact consistent money and blocks disabled or exhausted generation', () => {
  assert.doesNotThrow(() => assertAiBudget(budget));
  assert.equal(canGenerateAi(budget), true);
  assert.equal(canGenerateAi({...budget, enabled:false}), false);
  assert.equal(canGenerateAi({...budget, remaining_pln:'0.99'}), false);
  assert.equal(canGenerateAi(undefined), false);
  for (const update of [{budget_pln:50}, {remaining_pln:'47'}, {remaining_pln:'47.001'}, {reserved_pln:'4.00'}, {remaining_pln:'-1.00'}, {enabled:'true'}, {reservation_per_attempt_pln:'0.00'}]) assert.throws(() => assertAiBudget({...budget, ...update}));
});

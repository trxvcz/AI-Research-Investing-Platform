import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {assertAiHistoryContext,assertAiHistoryNarrative,canonicalContextJson,verifyAiHistoryContextHash} from '../src/ai-history-context.ts';
import {verifyAiRecord,verifyAiRecordList} from '../src/ai-analysis-state.ts';

const id='bd3c4552-1e4d-417b-8279-6a004595e0bb';
const source={source_id:'sec-edgar-revenue-v1',snapshot_id:'08f94ea4-bb8f-4bb6-9110-fc267dd5cb89',sha256:'b'.repeat(64),url:'https://data.sec.gov/api/xbrl/companyconcept/CIK0000000123/us-gaap/Revenues.json',retrieved_at:'2026-11-11T10:00:00Z',license:'Źródło testowe — dane publiczne 😀'};
const report={report_id:id,revision:1,checksum:'a'.repeat(64),input:{as_of:'2026-11-11T10:00:00Z',observations:[{status:'available',metric:'revenue',unit:'currency',currency:'USD',value:150,period_start:'2025-01-01T00:00:00Z',period_end:'2025-12-31T00:00:00Z',available_at:source.retrieved_at,source_id:source.source_id,snapshot_id:source.snapshot_id}]},sources:[source]};
function fixture() {
  const current={kind:'fact',index:0,metric:'revenue',unit:'currency',currency:'USD',value:'150',period_start:'2025-01-01T00:00:00Z',period_end:'2025-12-31T00:00:00Z',available_at:source.retrieved_at,source,report_observation_index:0,filing_accession:'0000000123-26-000001'};
  const previous={...current,index:1,value:'100',period_start:'2024-01-01T00:00:00Z',period_end:'2024-12-31T00:00:00Z',report_observation_index:null};
  const comparison={kind:'comparison',index:2,metric:'revenue',previous_index:1,current_index:0,delta_value:'50',delta_percent:'50.000000',comparison_reason:null};
  return seal({context_version:'report-history-context-v1',report_id:id,revision:1,report_checksum:report.checksum,as_of:report.input.as_of,methodology_version:'sec-comparatives-v1',evidence:[current,previous,comparison],limitations:['Brak pełnej wyceny; zachowano źródła 😀.'],context_sha256:'0'.repeat(64)});
}
function seal(value) {value.context_sha256=createHash('sha256').update(canonicalContextJson(value),'utf8').digest('hex');return value;}
function narrative() {return {summary:[{kind:'trend',text:'Przychody wzrosły względem poprzedniego okresu.',evidence_indexes:[2],direction:'increase'}],strengths:[],risks:[],questions:[{kind:'question',text:'Co wpłynęło na zmianę przychodów?',evidence_indexes:[2],direction:null}],limitations:['Brak danych o wycenie.']};}
function record(context=fixture()) {return {request_id:'17927fca-b046-4819-8d23-9a5c900748d8',report_id:id,revision:1,report_checksum:report.checksum,status:'completed',created_at:'2026-11-11T10:01:00Z',finished_at:'2026-11-11T10:01:02Z',model_id:'synthetic-model',prompt_version:'report-history-v2',analysis:narrative(),error_code:null,reserved_pln:'1.00',evidence_context:context};}

test('frozen history is bound to report, source, original value and availability',async()=>{
  const context=fixture();
  assert.doesNotThrow(()=>assertAiHistoryContext(context,report));
  await assert.doesNotReject(()=>verifyAiHistoryContextHash(context));
  for(const change of [{report_id:'other'},{revision:2},{report_checksum:'c'.repeat(64)},{as_of:'2026-11-12T10:00:00Z'}]) assert.throws(()=>assertAiHistoryContext(seal({...fixture(),...change}),report));
  for(const change of [{value:'151'},{period_end:'2025-12-30T00:00:00Z'},{available_at:'2026-11-12T10:00:00Z'},{report_observation_index:1},{source:{...source,sha256:'c'.repeat(64)}}]) {
    const value=fixture();Object.assign(value.evidence[0],change);assert.throws(()=>assertAiHistoryContext(seal(value),report));
  }
});

test('network verification checks SHA-256 after structural checks for running and terminal v2',async()=>{
  await assert.doesNotReject(()=>verifyAiRecord(record(),report,new Set([0])));
  const altered=record();altered.evidence_context.limitations[0]='Zmienione po zapisaniu.';
  await assert.rejects(()=>verifyAiRecord(altered,report,new Set([0])));
  const running={...record(),status:'running',finished_at:null,analysis:null};
  await assert.doesNotReject(()=>verifyAiRecord(running,report,new Set([0])));
  running.evidence_context.context_sha256='f'.repeat(64);
  await assert.rejects(()=>verifyAiRecord(running,report,new Set([0])));
  await assert.rejects(()=>verifyAiRecordList([record(),record()],report,new Set([0])));
});

test('exact comparison arithmetic, year gaps and nonpositive bases are not relabelled',()=>{
  for(const change of [{delta_value:'49'},{delta_percent:'49.999999'},{previous_index:2},{current_index:63},{metric:'net_income'}]) {
    const value=fixture();Object.assign(value.evidence[2],change);assert.throws(()=>assertAiHistoryContext(seal(value),report));
  }
  const zero=fixture();zero.evidence[1].value='0';Object.assign(zero.evidence[2],{delta_value:'150',delta_percent:null,comparison_reason:'NON_POSITIVE_BASE'});
  assert.doesNotThrow(()=>assertAiHistoryContext(seal(zero),report));
  zero.evidence[2].delta_percent='0.000000';assert.throws(()=>assertAiHistoryContext(seal(zero),report));
  const gap=fixture();Object.assign(gap.evidence[1],{period_start:'2023-01-01T00:00:00Z',period_end:'2023-12-31T00:00:00Z'});Object.assign(gap.evidence[2],{delta_value:null,delta_percent:null,comparison_reason:'PERIODS_NOT_COMPARABLE'});
  assert.doesNotThrow(()=>assertAiHistoryContext(seal(gap),report));
  assert.throws(()=>assertAiHistoryNarrative(narrative(),gap));
});

test('trend type and direction must match a single frozen comparison',()=>{
  const context=fixture();assert.doesNotThrow(()=>assertAiHistoryNarrative(narrative(),context));
  for(const change of [{direction:'decrease'},{evidence_indexes:[0]},{evidence_indexes:[2,0]},{evidence_indexes:[99]},{kind:'state',direction:null}]) {
    const value=narrative();Object.assign(value.summary[0],change);assert.throws(()=>assertAiHistoryNarrative(value,context));
  }
  for(const text of ['Przychody wzrosły o 50%.','Kup akcje.','<b>Wzrost</b>','https://evil.invalid']) {
    const value=narrative();value.summary[0].text=text;assert.throws(()=>assertAiHistoryNarrative(value,context));
  }
  const value=narrative();value.questions[0].kind='state';assert.throws(()=>assertAiHistoryNarrative(value,context));
});

test('dense references, same filing and all original observations must be preserved',()=>{
  for(const mutate of [value=>value.evidence[1].index=5,value=>value.evidence[1].filing_accession=null,value=>value.evidence[1].filing_accession='0000000123-26-000002',value=>value.evidence[0].report_observation_index=null,value=>value.evidence.push({...value.evidence[2],index:3})]) {
    const value=fixture();mutate(value);assert.throws(()=>assertAiHistoryContext(seal(value),report));
  }
  const extra=fixture();extra.internal_secret='rejected even with recomputed hash';assert.throws(()=>assertAiHistoryContext(seal(extra),report));
});

test('canonical JSON is ordered independently and Unicode hash is stable',async()=>{
  const value=fixture();const shuffled=Object.fromEntries(Object.entries(value).reverse());
  assert.equal(canonicalContextJson(shuffled),canonicalContextJson(value));
  assert.equal(value.context_sha256,'90db44113fdd3ca1061b07e96abe5a82d556f629c32c24dcdc80e681b82b9ff9');
  await assert.doesNotReject(()=>verifyAiHistoryContextHash(value));
});

import test from 'node:test';
import assert from 'node:assert/strict';
import {assertFinancialHistory,comparisonExplanation,formatHistoryDecimal} from '../src/financial-history-state.ts';

const snapshot='f1395e46-b70e-4798-9b9c-1f0db2a4d750';
const url='https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/Revenues.json';
const report={report_id:'a07344e2-17b1-490a-bde3-96dd03616e91',revision:2,checksum:'a'.repeat(64),input:{as_of:'2026-02-02T00:00:00Z'},sources:[{snapshot_id:snapshot,sha256:'b'.repeat(64),url,retrieved_at:'2026-02-01T12:00:00Z'}]};
const point=(year,value,delta_value=null,delta_percent=null,comparison_reason='NO_PRIOR_PERIOD')=>({period_start:year+'-01-01',period_end:year+'-12-31',value,filing_date:'2026-02-01',delta_value,delta_percent,comparison_reason});
const fixture=()=>({report_id:report.report_id,revision:2,report_checksum:report.checksum,as_of:report.input.as_of,methodology_version:'sec-comparatives-v1',basis:'latest_filing_comparatives',series:[{metric:'revenue',currency:'USD',status:'available',reason:null,source_snapshot_id:snapshot,source_sha256:'b'.repeat(64),source_url:url,available_at:'2026-02-01T12:00:00Z',filing_accession:'0000320193-26-000001',points:[point('2023','100'),point('2024','120','20','20.000000',null),point('2025','90','-30','-25.000000',null)]}],limitations:['Dane porównawcze z jednego sprawozdania.']});
const accept=value=>assertFinancialHistory(value,report);

test('history binds exact report revision, source bytes and cutoff',()=>{
  assert.doesNotThrow(()=>accept(fixture()));
  for(const update of [{report_id:'other'},{revision:1},{report_checksum:'c'.repeat(64)},{as_of:'2026-02-03T00:00:00Z'},{methodology_version:'future'},{basis:'historical_first_publication'}]) assert.throws(()=>accept({...fixture(),...update}));
  for(const update of [{source_snapshot_id:'unknown'},{source_sha256:'c'.repeat(64)},{source_url:'https://evil.invalid/'},{available_at:'2026-02-02T00:00:00Z'}]) {
    const value=fixture();Object.assign(value.series[0],update);assert.throws(()=>accept(value));
  }
});

test('missing or partial history is explicit and never filled with zero',()=>{
  const missing=fixture();Object.assign(missing.series[0],{status:'unavailable',reason:'HISTORY_NOT_AVAILABLE',filing_accession:null,points:[]});
  assert.doesNotThrow(()=>accept(missing));
  const partial=fixture();Object.assign(partial.series[0],{status:'partial',reason:'ONLY_TWO_PERIODS',points:partial.series[0].points.slice(0,2)});
  assert.doesNotThrow(()=>accept(partial));
  missing.series[0].points=[point('2025','0')];assert.throws(()=>accept(missing));
  partial.series[0].reason=null;assert.throws(()=>accept(partial));
});

test('zero and negative bases keep absolute change but abstain from percent',()=>{
  for(const base of ['0','-100']) {
    const value=fixture();const delta=base==='0'?'100':'200';
    Object.assign(value.series[0],{status:'partial',reason:'ONLY_TWO_PERIODS',points:[point('2024',base),point('2025','100',delta,null,'NON_POSITIVE_BASE')]});
    assert.doesNotThrow(()=>accept(value));
    value.series[0].points[1].delta_percent='100.000000';assert.throws(()=>accept(value));
  }
  assert.match(comparisonExplanation('NON_POSITIVE_BASE'),/zerowa lub ujemna/);
});

test('invalid arithmetic, missing values and imprecise numeric JSON are rejected',()=>{
  for(const update of [{value:120},{value:'NaN'},{value:'1e3'},{value:'Infinity'},{value:'0120'},{delta_value:'21'},{delta_percent:'999.000000'},{delta_percent:'20.0'},{comparison_reason:'NON_POSITIVE_BASE'}]) {
    const value=fixture();Object.assign(value.series[0].points[1],update);assert.throws(()=>accept(value));
  }
});

test('percent verification uses exact half-even rounding without binary floats',()=>{
  for(const [next,delta,percent] of [['200000001','1','0.000000'],['200000003','3','0.000002']]) {
    const value=fixture();Object.assign(value.series[0],{status:'partial',reason:'ONLY_TWO_PERIODS',points:[point('2024','200000000'),point('2025',next,delta,percent,null)]});
    assert.doesNotThrow(()=>accept(value));
  }
});

test('noncalendar fiscal periods and 52/53 week comparisons are supported',()=>{
  const value=fixture();
  const first={...point('2023','100'),period_start:'2023-01-01',period_end:'2023-12-30'};
  const second={...point('2024','120','20','20.000000',null),period_start:'2023-12-31',period_end:'2025-01-04'};
  Object.assign(value.series[0],{status:'partial',reason:'ONLY_TWO_PERIODS',points:[first,second]});
  assert.doesNotThrow(()=>accept(value));
});

test('gaps and changed fiscal duration abstain, while overlap and duplicate periods fail',()=>{
  const gap=fixture();Object.assign(gap.series[0],{status:'partial',reason:'ONLY_TWO_PERIODS',points:[point('2023','100'),point('2025','90',null,null,'PERIODS_NOT_COMPARABLE')]});
  assert.doesNotThrow(()=>accept(gap));
  gap.series[0].points[1].delta_value='-10';assert.throws(()=>accept(gap));
  for(const update of [{period_start:'2023-12-31'},{period_end:'2024-02-30'},{filing_date:'2027-01-01'},{filing_date:'2024-01-01'}]) {
    const value=fixture();Object.assign(value.series[0].points[1],update);assert.throws(()=>accept(value));
  }
  const duplicate=fixture();duplicate.series[0].points[1]=duplicate.series[0].points[0];assert.throws(()=>accept(duplicate));
});

test('bounded series and source protocols reject ambiguous response structure',()=>{
  for(const update of [{currency:'PLN'},{metric:'unknown'},{metric:'net_income'},{status:'complete'},{filing_accession:'bad'},{reason:'unexpected'}]) {
    const value=fixture();Object.assign(value.series[0],update);assert.throws(()=>accept(value));
  }
  const duplicates=fixture();duplicates.series.push(duplicates.series[0]);assert.throws(()=>accept(duplicates));
  for(const source_url of ['http://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/Revenues.json',url+'?key=secret',url.replace('data.sec.gov','data.sec.gov.evil.invalid')]) {
    const value=fixture();value.series[0].source_url=source_url;assert.throws(()=>accept(value));
  }
});

test('availability keeps microsecond precision and rejects impossible timestamps',()=>{
  const value=fixture();value.as_of='2026-02-02T00:00:00.000001Z';assert.throws(()=>accept(value));
  value.as_of='2026-02-30T00:00:00Z';assert.throws(()=>accept(value));
});

test('exact display preserves every monetary digit and decimal place',()=>{
  assert.equal(formatHistoryDecimal('123456789012345678901234567890.123450').replace(/[\s\u00a0]/g,''),'123456789012345678901234567890,123450');
  assert.equal(formatHistoryDecimal('-12345678901234567890.000001').replace(/[\s\u00a0]/g,''),'-12345678901234567890,000001');
  assert.equal(formatHistoryDecimal('0'),'0');assert.equal(formatHistoryDecimal('-0.000000'),'0,000000');
  assert.throws(()=>formatHistoryDecimal('1e100'));
});

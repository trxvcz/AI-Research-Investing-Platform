import test from 'node:test';
import assert from 'node:assert/strict';
import {assertFinancialRatios,ratioExplanation} from '../src/financial-ratios-state.ts';
const tags={revenue:'Revenues',net_income:'NetIncomeLoss',operating_cash_flow:'NetCashProvidedByUsedInOperatingActivities',capital_expenditures:'PaymentsToAcquirePropertyPlantAndEquipment'};
const names=Object.keys(tags),ratioNames=['net_margin','operating_cash_flow_margin','capex_to_revenue','free_cash_flow_margin'];
const required=[['revenue','net_income'],['revenue','operating_cash_flow'],['revenue','capital_expenditures'],['revenue','operating_cash_flow','capital_expenditures']];
const start='2025-01-01',end='2025-12-31';
function fixture(values=['100','25','30','10']){
 const series=names.map((metric,index)=>({metric,currency:'USD',status:'partial',reason:'ONLY_ONE_PERIOD',source_snapshot_id:'00000000-0000-4000-8000-00000000000'+index,source_sha256:String(index+1).repeat(64),source_url:'https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/'+tags[metric]+'.json',available_at:'2026-02-01T12:00:00.00000'+index+'Z',filing_accession:'0000320193-26-000001',points:[{period_start:start,period_end:end,value:values[index],filing_date:'2026-02-01',delta_value:null,delta_percent:null,comparison_reason:'NO_PRIOR_PERIOD'}]}));
 const report={report_id:'00000000-0000-4000-8000-000000000099',revision:1,checksum:'f'.repeat(64),input:{as_of:'2026-02-02T00:00:00Z'},sources:series.map(s=>({snapshot_id:s.source_snapshot_id,sha256:s.source_sha256,url:s.source_url,retrieved_at:s.available_at}))};
 const history={report_id:report.report_id,revision:1,report_checksum:report.checksum,as_of:report.input.as_of,methodology_version:'sec-comparatives-v1',basis:'latest_filing_comparatives',series,limitations:['Synthetic comparison only.']};
 const ratios=ratioNames.map((metric,index)=>({metric,period_start:start,period_end:end,status:'available',value_percent:['25.000000','30.000000','10.000000','20.000000'][index],reason:null,available_at:series[names.indexOf(required[index].at(-1))].available_at,operands:required[index].map(name=>{const s=series.find(item=>item.metric===name);return {metric:name,value:s.points[0].value,source_snapshot_id:s.source_snapshot_id,source_sha256:s.source_sha256};})}));
 return {report,value:{report_id:report.report_id,revision:1,report_checksum:report.checksum,as_of:report.input.as_of,methodology_version:'sec-ratios-v1',history,ratios,limitations:['Not a valuation.']}};
}
function accept({value,report}){assertFinancialRatios(value,report);}
function unavailable(point,reason){Object.assign(point,{status:'unavailable',reason,value_percent:null,available_at:null});}
function syncOperands(f){for(const point of f.value.ratios)for(const operand of point.operands)operand.value=f.value.history.series.find(s=>s.metric===operand.metric).points[0].value;}

test('ratios are bound to full history and report identity; subset/order cannot hide a missing ratio',()=>{
 assert.doesNotThrow(()=>accept(fixture()));
 for(const update of [{report_id:'other'},{revision:2},{report_checksum:'b'.repeat(64)},{as_of:'2026-02-02T00:00:00.000001Z'},{methodology_version:'other'}]){const f=fixture();Object.assign(f.value,update);assert.throws(()=>accept(f));}
 for(const mutation of [f=>f.value.ratios.pop(),f=>f.value.ratios.push(f.value.ratios[0]),f=>f.value.ratios[1]=f.value.ratios[0],f=>f.value.history.series[0].source_sha256='a'.repeat(64)]){const f=fixture();mutation(f);assert.throws(()=>accept(f));}
 const f=fixture();f.value.ratios.reverse();assert.doesNotThrow(()=>accept(f));
});

test('exact arithmetic preserves large decimal operands and rejects Number or altered result',()=>{
 for(const update of [{value_percent:'25.0'},{value_percent:'26.000000'},{value_percent:25},{status:'unavailable'},{reason:'MISSING_INPUT'},{period_start:'2024-01-01'}]){const f=fixture();Object.assign(f.value.ratios[0],update);assert.throws(()=>accept(f));}
 for(const update of [{metric:'revenue'},{value:'26'},{value:25},{source_snapshot_id:'other'},{source_sha256:'e'.repeat(64)}]){const f=fixture();Object.assign(f.value.ratios[0].operands[1],update);assert.throws(()=>accept(f));}
 const f=fixture(['100000000000000000000000000000000000000','25000000000000000000000000000000000000','30000000000000000000000000000000000000','10000000000000000000000000000000000000']);assert.doesNotThrow(()=>accept(f));
});

test('negative numerators remain negative and percentage rounds ties HALF_EVEN including canonical zero',()=>{
 for(const [income,expected] of [['1','0.000000'],['3','0.000002'],['-1','0.000000'],['-3','-0.000002']]){
  const f=fixture(['200000000',income,'30','10']);f.value.ratios[0].value_percent=expected;f.value.ratios[1].value_percent='0.000015';f.value.ratios[2].value_percent='0.000005';f.value.ratios[3].value_percent='0.000010';assert.doesNotThrow(()=>accept(f));
  f.value.ratios[0].value_percent=expected==='0.000000'?'-0.000000':'0.000000';assert.throws(()=>accept(f));
 }
 const f=fixture(['100','-25','-30','10']);f.value.ratios[0].value_percent='-25.000000';f.value.ratios[1].value_percent='-30.000000';f.value.ratios[3].value_percent='-40.000000';assert.doesNotThrow(()=>accept(f));
});

test('nonpositive revenue blocks all ratios; negative capex blocks only formulas using capex',()=>{
 for(const revenue of ['0','-100']){const f=fixture([revenue,'25','30','10']);f.value.ratios.forEach(p=>unavailable(p,'NON_POSITIVE_REVENUE'));assert.doesNotThrow(()=>accept(f));f.value.ratios[0].value_percent='0.000000';assert.throws(()=>accept(f));}
 const f=fixture(['100','25','30','-10']);unavailable(f.value.ratios[2],'NEGATIVE_CAPEX');unavailable(f.value.ratios[3],'NEGATIVE_CAPEX');assert.doesNotThrow(()=>accept(f));
});

test('missing and empty series are explicit MISSING_INPUT before period mismatch',()=>{
 for(const empty of [false,true]){
  const f=fixture();if(empty)Object.assign(f.value.history.series[1],{points:[],status:'unavailable',reason:'NO_HISTORY',filing_accession:null});else f.value.history.series.splice(1,1);
  f.value.ratios[0].operands=f.value.ratios[0].operands.filter(o=>o.metric!=='net_income');unavailable(f.value.ratios[0],'MISSING_INPUT');assert.doesNotThrow(()=>accept(f));
  f.value.ratios[0].reason='PERIOD_MISMATCH';assert.throws(()=>accept(f));
 }
 const f=fixture();f.value.history.series=[];f.value.ratios=[];assert.doesNotThrow(()=>accept(f));f.value.ratios=[fixture().value.ratios[0]];assert.throws(()=>accept(f));
});

test('different filing blocks matching periods; fabricated availability and future history fail',()=>{
 const f=fixture();f.value.history.series[1].filing_accession='0000320193-26-000002';unavailable(f.value.ratios[0],'FILING_MISMATCH');assert.doesNotThrow(()=>accept(f));f.value.ratios[0].reason='PERIOD_MISMATCH';assert.throws(()=>accept(f));
 for(const raw of ['2026-02-01T12:00:00Z','2026-02-02T00:00:00Z','2026-02-30T00:00:00Z']){const changed=fixture();changed.value.ratios[0].available_at=raw;assert.throws(()=>accept(changed));}
 const changed=fixture();changed.value.history.as_of='2027-01-01T00:00:00Z';assert.throws(()=>accept(changed));
});

test('period mismatch is not silently combined and every union period has four explicit points',()=>{
 const f=fixture();const source=f.value.history.series[1];Object.assign(source.points[0],{period_start:'2024-01-01',period_end:'2024-12-31'});
 unavailable(f.value.ratios[0],'PERIOD_MISMATCH');f.value.ratios[0].operands=f.value.ratios[0].operands.filter(o=>o.metric!=='net_income');
 const past=structuredClone(fixture().value.ratios);past.forEach(p=>{p.period_start='2024-01-01';p.period_end='2024-12-31';p.operands=p.metric==='net_margin'?[{metric:'net_income',value:'25',source_snapshot_id:source.source_snapshot_id,source_sha256:source.source_sha256}]:[];unavailable(p,'PERIOD_MISMATCH');});
 f.value.ratios.push(...past);assert.doesNotThrow(()=>accept(f));
 f.value.ratios[0].reason='MISSING_INPUT';assert.throws(()=>accept(f));
});

test('reasons have clear explanations without ratings or trading instructions',()=>{
 for(const reason of ['MISSING_INPUT','PERIOD_MISMATCH','FILING_MISMATCH','NON_POSITIVE_REVENUE','NEGATIVE_CAPEX'])assert.ok(ratioExplanation(reason).length>10);
 assert.equal(ratioExplanation(null),'');
});

test('missing and filing reasons take precedence over invalid denominator and capex',()=>{
 const f=fixture(['0','25','30','-10']);f.value.history.series.splice(1,1);f.value.ratios[0].operands=f.value.ratios[0].operands.filter(o=>o.metric!=='net_income');unavailable(f.value.ratios[0],'MISSING_INPUT');
 f.value.history.series.find(s=>s.metric==='operating_cash_flow').filing_accession='0000320193-26-000002';
 unavailable(f.value.ratios[1],'FILING_MISMATCH');unavailable(f.value.ratios[2],'NON_POSITIVE_REVENUE');unavailable(f.value.ratios[3],'FILING_MISMATCH');assert.doesNotThrow(()=>accept(f));
 for(const [index,reason] of [[0,'NON_POSITIVE_REVENUE'],[1,'NON_POSITIVE_REVENUE'],[2,'NEGATIVE_CAPEX'],[3,'NEGATIVE_CAPEX']]){const changed=structuredClone(f);changed.value.ratios[index].reason=reason;assert.throws(()=>accept(changed));}
});

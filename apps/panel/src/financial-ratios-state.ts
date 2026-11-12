import {assertFinancialHistory} from './financial-history-state.ts';
import type {FinancialHistoryData,HistoryIdentity,HistorySeries,HistoryPoint} from './financial-history-state.ts';

export type RatioMetric='net_margin'|'operating_cash_flow_margin'|'capex_to_revenue'|'free_cash_flow_margin';
export type RatioReason='MISSING_INPUT'|'PERIOD_MISMATCH'|'FILING_MISMATCH'|'NON_POSITIVE_REVENUE'|'NEGATIVE_CAPEX';
export type RatioOperand={metric:HistorySeries['metric'];value:string;source_snapshot_id:string;source_sha256:string};
export type FinancialRatio={metric:RatioMetric;period_start:string;period_end:string;status:'available'|'unavailable';value_percent:string|null;reason:RatioReason|null;available_at:string|null;operands:RatioOperand[]};
export type FinancialRatiosData={report_id:string;revision:number;report_checksum:string;as_of:string;methodology_version:'sec-ratios-v1';history:FinancialHistoryData;ratios:FinancialRatio[];limitations:string[]};
export const ratioLabels:Record<RatioMetric,string>={net_margin:'Marża netto',operating_cash_flow_margin:'Przepływy operacyjne / przychody',capex_to_revenue:'Nakłady / przychody',free_cash_flow_margin:'(Przepływy operacyjne − nakłady) / przychody'};
export const ratioFormulas:Record<RatioMetric,string>={net_margin:'wynik netto / przychody × 100',operating_cash_flow_margin:'przepływy operacyjne / przychody × 100',capex_to_revenue:'nakłady / przychody × 100',free_cash_flow_margin:'(przepływy operacyjne − nakłady) / przychody × 100'};
const required:Record<RatioMetric,HistorySeries['metric'][]>={net_margin:['revenue','net_income'],operating_cash_flow_margin:['revenue','operating_cash_flow'],capex_to_revenue:['revenue','capital_expenditures'],free_cash_flow_margin:['revenue','operating_cash_flow','capital_expenditures']};
const object=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v);
const decimal=(v:unknown):v is string=>typeof v==='string'&&v.length<=128&&/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(v);
const text=(v:unknown):v is string=>typeof v==='string'&&v.trim().length>0&&v.length<=1200;
function fail():never {throw Error('Nieprawidłowe lub niespójne wskaźniki raportu.');}
const places=(v:string)=>v.split('.')[1]?.length??0;
function scaled(v:string,p:number):bigint {const [w,f='']=v.replace(/^-/,'').split('.');const n=BigInt(w+f.padEnd(p,'0'));return v.startsWith('-')?-n:n;}
function sameDecimal(a:string,b:string):boolean {const p=Math.max(places(a),places(b));return scaled(a,p)===scaled(b,p);}
function instant(raw:string):bigint {
  const match=/^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-](\d{2}):(\d{2}))$/.exec(raw);
  if(!match||Number(match[2])>23||Number(match[3])>59||Number(match[4])>59||(match[6]!=='Z'&&(Number(match[7])>23||Number(match[8])>59))) return fail();
  const ms=Date.parse(raw);if(!Number.isFinite(ms)||new Date(Date.parse(match[1]+'T00:00:00Z')).toISOString().slice(0,10)!==match[1]) return fail();
  return BigInt(ms)*1000n+BigInt((match[5]??'').padEnd(6,'0').slice(3));
}
/** HALF_EVEN percentage in millionths; never converts amounts to Number. */
function percentage(n:bigint,d:bigint):string {
  const negative=n<0n;const absolute=(negative?-n:n)*100000000n;let value=absolute/d;const remainder=absolute%d;
  if(remainder*2n>d||(remainder*2n===d&&value%2n!==0n))value++;
  const digits=value.toString().padStart(7,'0');return (negative&&value!==0n?'-':'')+digits.slice(0,-6)+'.'+digits.slice(-6);
}

export function assertFinancialRatios(value:unknown,report:HistoryIdentity):asserts value is FinancialRatiosData {
  if(!object(value)||value.report_id!==report.report_id||value.revision!==report.revision||value.report_checksum!==report.checksum||value.methodology_version!=='sec-ratios-v1'||typeof value.as_of!=='string'||instant(value.as_of)!==instant(report.input.as_of))fail();
  assertFinancialHistory(value.history,report);
  const history=value.history;
  if(!Array.isArray(value.ratios)||value.ratios.length>12||!Array.isArray(value.limitations)||value.limitations.length<1||value.limitations.length>16||value.limitations.some(v=>!text(v)))fail();
  const periods=[...new Set(history.series.flatMap(s=>s.points.map(p=>p.period_start+'|'+p.period_end)))].sort().slice(-3);
  if(value.ratios.length!==periods.length*4)fail();
  const seen=new Set<string>();
  for(const raw of value.ratios){
    if(!object(raw)||typeof raw.metric!=='string'||!Object.hasOwn(required,raw.metric)||typeof raw.period_start!=='string'||typeof raw.period_end!=='string'||!Array.isArray(raw.operands)||raw.operands.length>3)fail();
    const metric=raw.metric as RatioMetric,period=raw.period_start+'|'+raw.period_end,key=period+'|'+metric;
    if(!periods.includes(period)||seen.has(key))fail();seen.add(key);
    const selected=required[metric].map(name=>{const series=history.series.find(s=>s.metric===name);return {metric:name,series,point:series?.points.find(p=>p.period_start===raw.period_start&&p.period_end===raw.period_end)};});
    const expected=selected.filter((item):item is {metric:HistorySeries['metric'];series:HistorySeries;point:HistoryPoint}=>!!item.series&&!!item.point);
    if(raw.operands.length!==expected.length)fail();
    const operandSeen=new Set<string>();
    for(const operand of raw.operands){
      if(!object(operand)||typeof operand.metric!=='string'||operandSeen.has(operand.metric)||!decimal(operand.value))fail();operandSeen.add(operand.metric);
      const bound=expected.find(item=>item.metric===operand.metric);
      if(!bound||!sameDecimal(operand.value,bound.point.value)||operand.source_snapshot_id!==bound.series.source_snapshot_id||operand.source_sha256!==bound.series.source_sha256)fail();
    }
    let reason:RatioReason|null=null;
    if(selected.some(item=>!item.series||item.series.points.length===0))reason='MISSING_INPUT';
    else if(selected.some(item=>!item.point))reason='PERIOD_MISMATCH';
    else if(selected.some(item=>!item.series!.filing_accession)||new Set(selected.map(item=>item.series!.filing_accession)).size!==1)reason='FILING_MISMATCH';
    const scale=Math.max(0,...expected.map(item=>places(item.point.value)));
    const amounts=new Map(expected.map(item=>[item.metric,scaled(item.point.value,scale)]));
    if(!reason&&(amounts.get('revenue')??0n)<=0n)reason='NON_POSITIVE_REVENUE';
    if(!reason&&required[metric].includes('capital_expenditures')&&(amounts.get('capital_expenditures')??0n)<0n)reason='NEGATIVE_CAPEX';
    if(reason){if(raw.status!=='unavailable'||raw.reason!==reason||raw.value_percent!==null||raw.available_at!==null)fail();continue;}
    if(raw.status!=='available'||raw.reason!==null||typeof raw.value_percent!=='string'||raw.value_percent.length>128||! /^-?(?:0|[1-9][0-9]*)\.[0-9]{6}$/.test(raw.value_percent)||typeof raw.available_at!=='string')fail();
    const numerator=metric==='net_margin'?amounts.get('net_income')!:metric==='operating_cash_flow_margin'?amounts.get('operating_cash_flow')!:metric==='capex_to_revenue'?amounts.get('capital_expenditures')!:amounts.get('operating_cash_flow')!-amounts.get('capital_expenditures')!;
    if(raw.value_percent!==percentage(numerator,amounts.get('revenue')!))fail();
    const availability=expected.map(item=>instant(item.series.available_at)).reduce((a,b)=>a>b?a:b);
    if(instant(raw.available_at)!==availability)fail();
  }
}
export function ratioExplanation(reason:RatioReason|null):string {return reason===null?'':({MISSING_INPUT:'Brakuje wymaganej metryki w archiwum.',PERIOD_MISMATCH:'Składniki nie obejmują dokładnie tego samego okresu.',FILING_MISMATCH:'Składniki nie pochodzą z tego samego zidentyfikowanego sprawozdania.',NON_POSITIVE_REVENUE:'Przychody są zerowe lub ujemne; nie wyliczamy wskaźnika.',NEGATIVE_CAPEX:'Nakłady mają ujemny znak; nie wyliczamy wskaźnika.'}[reason]);}



export type HistoryPoint = {period_start:string; period_end:string; value:string; filing_date:string; delta_value:string|null; delta_percent:string|null; comparison_reason:'NO_PRIOR_PERIOD'|'PERIODS_NOT_COMPARABLE'|'NON_POSITIVE_BASE'|null};
export type HistorySeries = {metric:'revenue'|'net_income'|'operating_cash_flow'|'capital_expenditures'; currency:'USD'; status:'available'|'partial'|'unavailable'; reason:string|null; source_snapshot_id:string; source_sha256:string; source_url:string; available_at:string; filing_accession:string|null; points:HistoryPoint[]};
export type FinancialHistoryData = {report_id:string; revision:number; report_checksum:string; as_of:string; methodology_version:'sec-comparatives-v1'; basis:'latest_filing_comparatives'; series:HistorySeries[]; limitations:string[]};
export type HistoryIdentity = {report_id:string; revision:number; checksum:string; input:{as_of:string}; sources:{snapshot_id:string; sha256:string; url:string|null; retrieved_at:string}[]};
const object = (value:unknown):value is Record<string,unknown> => !!value && typeof value==='object' && !Array.isArray(value);
const text = (value:unknown):value is string => typeof value==='string' && value.trim().length>0 && value.length<=1200;
const decimal = (value:unknown):value is string => typeof value==='string' && value.length<=128 && /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(value);
const hash = /^[a-f0-9]{64}$/;
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const metrics = new Set(['revenue','net_income','operating_cash_flow','capital_expenditures']);
const sourceUrl = /^https:\/\/data\.sec\.gov\/api\/xbrl\/companyconcept\/CIK[0-9]{10}\/us-gaap\/(?:RevenueFromContractWithCustomerExcludingAssessedTax|Revenues|SalesRevenueNet|NetIncomeLoss|NetCashProvidedByUsedInOperatingActivities|PaymentsToAcquirePropertyPlantAndEquipment)\.json$/;
const tags:Record<string,readonly string[]>={revenue:['RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet'],net_income:['NetIncomeLoss'],operating_cash_flow:['NetCashProvidedByUsedInOperatingActivities'],capital_expenditures:['PaymentsToAcquirePropertyPlantAndEquipment']};
function fail():never {throw Error('Nieprawidłowe lub niespójne dane porównawcze raportu.');}

function day(raw:unknown):number {
  if(typeof raw!=='string' || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(raw) || raw.startsWith('0000')) return fail();
  const value=Date.parse(raw+'T00:00:00Z');
  if(!Number.isFinite(value) || new Date(value).toISOString().slice(0,10)!==raw) return fail();
  return value/86400000;
}
function instant(raw:string):bigint {
  const match=/^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-](\d{2}):(\d{2}))$/.exec(raw);
  if(!match) return fail();
  day(match[1]);
  const milliseconds=Date.parse(raw);
  if(Number(match[2])>23 || Number(match[3])>59 || Number(match[4])>59 || (match[6]!=='Z' && (Number(match[7])>23 || Number(match[8])>59)) || !Number.isFinite(milliseconds)) return fail();
  return BigInt(milliseconds)*1000n+BigInt((match[5]??'').padEnd(6,'0').slice(3));
}
function checkChronology(earlier:string,later:string):void {
  if(instant(earlier)>instant(later)) fail();
}
function scaled(value:string, places:number):bigint {
  const [whole,fraction='']=value.replace(/^-/,'').split('.');
  const result=BigInt(whole+fraction.padEnd(places,'0'));
  return value.startsWith('-') ? -result : result;
}
const places = (value:string) => value.split('.')[1]?.length??0;
function equalDecimal(a:string,b:string):boolean {
  const scale=Math.max(places(a),places(b));
  return scaled(a,scale)===scaled(b,scale);
}
function expectedPercent(delta:bigint, previous:bigint):bigint {
  const negative=delta<0n;
  const numerator=(negative?-delta:delta)*100000000n;
  let rounded=numerator/previous;
  const remainder=numerator%previous;
  if(remainder*2n>previous || (remainder*2n===previous && rounded%2n===1n)) rounded++;
  return negative?-rounded:rounded;
}

export function assertFinancialHistory(value:unknown, report:HistoryIdentity):asserts value is FinancialHistoryData {
  if(!object(value) || value.report_id!==report.report_id || value.revision!==report.revision || value.report_checksum!==report.checksum || !hash.test(report.checksum) || value.methodology_version!=='sec-comparatives-v1' || value.basis!=='latest_filing_comparatives' || typeof value.as_of!=='string') fail();
  checkChronology(value.as_of,report.input.as_of); checkChronology(report.input.as_of,value.as_of);
  if(!Array.isArray(value.series) || value.series.length>4 || !Array.isArray(value.limitations) || value.limitations.length<1 || value.limitations.length>16 || value.limitations.some(item=>!text(item))) fail();
  const seen=new Set<string>();
  for(const series of value.series) {
    if(!object(series) || typeof series.metric!=='string' || !metrics.has(series.metric) || seen.has(series.metric) || series.currency!=='USD' || !['available','partial','unavailable'].includes(String(series.status)) || (series.reason!==null&&!text(series.reason)) || typeof series.source_snapshot_id!=='string' || !uuid.test(series.source_snapshot_id) || typeof series.source_sha256!=='string' || !hash.test(series.source_sha256) || typeof series.source_url!=='string' || !sourceUrl.test(series.source_url) || typeof series.available_at!=='string' || !Array.isArray(series.points) || series.points.length>3) fail();
    seen.add(series.metric);
    const tag=series.source_url.split('/').at(-1)!.replace(/\.json$/,'');
    if(!tags[series.metric].includes(tag)) fail();
    checkChronology(series.available_at,value.as_of);
    const provenance=report.sources.find(source=>source.snapshot_id===series.source_snapshot_id);
    if(!provenance || provenance.sha256!==series.source_sha256 || provenance.url!==series.source_url) fail();
    checkChronology(series.available_at,provenance.retrieved_at); checkChronology(provenance.retrieved_at,series.available_at);
    if(series.status==='unavailable') {
      if(series.points.length!==0 || !text(series.reason) || series.filing_accession!==null) fail();
      continue;
    }
    if((series.status==='available' && (series.points.length!==3 || series.reason!==null)) || (series.status==='partial' && (series.points.length<1 || series.points.length>2 || !text(series.reason))) || typeof series.filing_accession!=='string' || !/^[0-9]{10}-[0-9]{2}-[0-9]{6}$/.test(series.filing_accession)) fail();
    let prior:HistoryPoint|undefined;
    for(const item of series.points) {
      if(!object(item) || !decimal(item.value) || (item.delta_value!==null&&!decimal(item.delta_value)) || (item.delta_percent!==null&&(!decimal(item.delta_percent)||!/-?[0-9]+\.[0-9]{6}$/.test(item.delta_percent)))) fail();
      const start=day(item.period_start),end=day(item.period_end),filed=day(item.filing_date);
      if(end-start<300 || end-start>400 || filed<end || filed>day(new Date(series.available_at).toISOString().slice(0,10))) fail();
      if(!prior) {
        if(item.delta_value!==null || item.delta_percent!==null || item.comparison_reason!=='NO_PRIOR_PERIOD') fail();
      } else {
        const previousEnd=day(prior.period_end),previousStart=day(prior.period_start);
        if(start<=previousEnd || item.filing_date!==prior.filing_date) fail();
        const comparable=start===previousEnd+1 && Math.abs((end-start)-(previousEnd-previousStart))<=8;
        if(!comparable) {
          if(item.comparison_reason!=='PERIODS_NOT_COMPARABLE' || item.delta_value!==null || item.delta_percent!==null) fail();
        } else {
          if(!decimal(item.delta_value)) fail();
          const scale=Math.max(places(item.value),places(prior.value),places(item.delta_value));
          const current=scaled(item.value,scale),previous=scaled(prior.value,scale),delta=current-previous;
          if(scaled(item.delta_value,scale)!==delta) fail();
          if(previous<=0n) {
            if(item.delta_percent!==null || item.comparison_reason!=='NON_POSITIVE_BASE') fail();
          } else if(item.comparison_reason!==null || !decimal(item.delta_percent) || scaled(item.delta_percent,6)!==expectedPercent(delta,previous)) fail();
        }
      }
      prior=item as unknown as HistoryPoint;
    }
  }
}

/** Display every digit, including values outside the safe JavaScript integer range. */
export function formatHistoryDecimal(value:string):string {
  if(!decimal(value)) return fail();
  const [whole,fraction]=value.replace(/^-/,'').split('.');
  const negative=value.startsWith('-') && !equalDecimal(value,'0');
  return (negative?'-':'')+new Intl.NumberFormat('pl-PL').format(BigInt(whole))+(fraction!==undefined?','+fraction:'');
}

export function comparisonExplanation(reason:HistoryPoint['comparison_reason']):string {
  return reason==='NO_PRIOR_PERIOD'?'Brak wcześniejszego okresu w tym zestawie.':reason==='NON_POSITIVE_BASE'?'Brak zmiany procentowej: poprzednia wartość jest zerowa lub ujemna.':reason==='PERIODS_NOT_COMPARABLE'?'Okresy są nieciągłe lub różnią się zakresem; nie wyliczamy zmiany.':'';
}

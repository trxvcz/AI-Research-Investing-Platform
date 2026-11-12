/** Frozen evidence validation; reading current history must never rebind a saved claim. */
export type AiHistorySource = {source_id:string; snapshot_id:string; sha256:string; url:string|null; retrieved_at:string; license:string};
export type AiHistoryFact = {kind:'fact'; index:number; metric:string; unit:string; currency:string|null; value:string; period_start:string; period_end:string; available_at:string; source:AiHistorySource; report_observation_index:number|null; filing_accession:string|null};
export type AiHistoryComparison = {kind:'comparison'; index:number; metric:string; previous_index:number; current_index:number; delta_value:string|null; delta_percent:string|null; comparison_reason:'NON_POSITIVE_BASE'|'PERIODS_NOT_COMPARABLE'|null};
export type AiHistoryEvidence = AiHistoryFact|AiHistoryComparison;
export type AiHistoryContext = {context_version:'report-history-context-v1'; report_id:string; revision:number; report_checksum:string; as_of:string; methodology_version:'sec-comparatives-v1'; evidence:AiHistoryEvidence[]; limitations:string[]; context_sha256:string};
export type AiHistoryClaim = {kind:'state'|'trend'|'question'; text:string; evidence_indexes:number[]; direction:'increase'|'decrease'|'unchanged'|null};
export type AiHistoryNarrative = {summary:AiHistoryClaim[]; strengths:AiHistoryClaim[]; risks:AiHistoryClaim[]; questions:AiHistoryClaim[]; limitations:string[]};

const object=(value:unknown):value is Record<string,unknown> => !!value&&typeof value==='object'&&!Array.isArray(value);
const text=(value:unknown,max:number):value is string => typeof value==='string'&&value.trim().length>0&&Array.from(value).length<=max;
const decimal=(value:unknown):value is string => typeof value==='string'&&value.length<=128&&/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(value);
const hash=/^[a-f0-9]{64}$/;
const metric=/^[a-z][a-z0-9_]{0,63}$/;
const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const accession=/^[0-9]{10}-[0-9]{2}-[0-9]{6}$/;
function fail():never {throw Error('Nieprawidłowy zamrożony kontekst analizy AI.');}
function keys(value:Record<string,unknown>,expected:string[]):void {
  if(Object.keys(value).sort().join('|')!==expected.sort().join('|')) fail();
}
function instant(value:unknown):bigint {
  if(typeof value!=='string') return fail();
  const match=/^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-](\d{2}):(\d{2}))$/.exec(value);
  if(!match||Number(match[2])>23||Number(match[3])>59||Number(match[4])>59||(match[6]!=='Z'&&(Number(match[7])>23||Number(match[8])>59))) return fail();
  const day=Date.parse(match[1]+'T00:00:00Z'),milliseconds=Date.parse(value);
  if(!Number.isFinite(day)||new Date(day).toISOString().slice(0,10)!==match[1]||!Number.isFinite(milliseconds)) return fail();
  return BigInt(milliseconds)*1000n+BigInt((match[5]??'').padEnd(6,'0').slice(3));
}
function sameTime(a:unknown,b:unknown):boolean {return instant(a)===instant(b);}
const places=(value:string)=>value.split('.')[1]?.length??0;
function scaled(value:string,scale:number):bigint {
  const [whole,fraction='']=value.replace(/^-/,'').split('.');
  const number=BigInt(whole+fraction.padEnd(scale,'0'));
  return value.startsWith('-')?-number:number;
}
function equal(a:string,b:string):boolean {const scale=Math.max(places(a),places(b));return scaled(a,scale)===scaled(b,scale);}
function numberDecimal(value:unknown):string {
  if(typeof value!=='number'||!Number.isFinite(value)) return fail();
  const raw=String(value);
  if(decimal(raw)) return raw;
  const match=/^(-?)([0-9]+)(?:\.([0-9]+))?e([+-]?[0-9]+)$/i.exec(raw);
  if(!match) return fail();
  const exponent=Number(match[4]), digits=match[2]+(match[3]??''), point=match[2].length+exponent;
  if(Math.abs(exponent)>127) return fail();
  const result=match[1]+(point<=0?'0.'+'0'.repeat(-point)+digits:point>=digits.length?digits+'0'.repeat(point-digits.length):digits.slice(0,point)+'.'+digits.slice(point));
  if(!decimal(result)) return fail();
  return result;
}
function source(value:unknown):asserts value is AiHistorySource {
  if(!object(value)) fail();
  keys(value,['source_id','snapshot_id','sha256','url','retrieved_at','license']);
  if(!text(value.source_id,128)||!text(value.snapshot_id,128)||typeof value.sha256!=='string'||!hash.test(value.sha256)||!text(value.license,512)||typeof value.url!=='string') fail();
  let url:URL;
  try {url=new URL(value.url);} catch {return fail();}
  if(url.protocol!=='https:'||!['data.sec.gov','www.sec.gov'].includes(url.hostname)||url.username||url.password||url.hash) fail();
  instant(value.retrieved_at);
}
function sameSource(a:AiHistorySource,b:AiHistorySource):boolean {
  return a.source_id===b.source_id&&a.snapshot_id===b.snapshot_id&&a.sha256===b.sha256&&a.url===b.url&&a.license===b.license&&sameTime(a.retrieved_at,b.retrieved_at);
}
function expectedPercent(delta:bigint,previous:bigint):bigint {
  const negative=delta<0n,numerator=(negative?-delta:delta)*100000000n;
  let rounded=numerator/previous;
  const remainder=numerator%previous;
  if(remainder*2n>previous||(remainder*2n===previous&&rounded%2n===1n)) rounded++;
  return negative?-rounded:rounded;
}
export function assertAiHistoryContext(value:unknown,report:unknown):asserts value is AiHistoryContext {
  if(!object(value)||!object(report)||!object(report.input)||!Array.isArray(report.input.observations)||!Array.isArray(report.sources)) fail();
  keys(value,['context_version','report_id','revision','report_checksum','as_of','methodology_version','evidence','limitations','context_sha256']);
  if(value.context_version!=='report-history-context-v1'||value.methodology_version!=='sec-comparatives-v1'||value.report_id!==report.report_id||value.revision!==report.revision||value.report_checksum!==report.checksum||typeof value.report_id!=='string'||!uuid.test(value.report_id)||typeof value.context_sha256!=='string'||!hash.test(value.context_sha256)||!Array.isArray(value.evidence)||value.evidence.length<1||value.evidence.length>64||!Array.isArray(value.limitations)||value.limitations.length<1||value.limitations.length>16||value.limitations.some(item=>!text(item,1200))) fail();
  if(!sameTime(value.as_of,report.input.as_of)) fail();
  const evidence:AiHistoryEvidence[]=[], original=new Set<number>(), factKeys=new Set<string>(), comparisonKeys=new Set<string>();
  for(const [index,item] of value.evidence.entries()) {
    if(!object(item)||item.index!==index||typeof item.metric!=='string'||!metric.test(item.metric)) fail();
    if(item.kind==='fact') {
      keys(item,['kind','index','metric','unit','currency','value','period_start','period_end','available_at','source','report_observation_index','filing_accession']);
      if(!text(item.unit,64)||(item.currency!==null&&(typeof item.currency!=='string'||! /^[A-Z]{3}$/.test(item.currency)))||!decimal(item.value)||(item.filing_accession!==null&&(typeof item.filing_accession!=='string'||!accession.test(item.filing_accession)))) fail();
      source(item.source);
      const frozenSource=item.source;
      if(instant(item.period_start)>instant(item.period_end)||instant(item.period_end)>instant(item.available_at)||instant(item.available_at)>instant(value.as_of)||!sameTime(item.available_at,item.source.retrieved_at)) fail();
      const provenance=report.sources.find(candidate=>object(candidate)&&candidate.source_id===frozenSource.source_id&&candidate.snapshot_id===frozenSource.snapshot_id);
      if(!provenance) fail();
      source(provenance);
      if(!sameSource(item.source,provenance)) fail();
      if(item.report_observation_index!==null) {
        if(!Number.isInteger(item.report_observation_index)||Number(item.report_observation_index)<0||original.has(Number(item.report_observation_index))) fail();
        const observation:unknown=report.input.observations[Number(item.report_observation_index)];
        if(!object(observation)||observation.status!=='available'||observation.metric!==item.metric||observation.unit!==item.unit||observation.currency!==item.currency||observation.source_id!==item.source.source_id||observation.snapshot_id!==item.source.snapshot_id||!sameTime(observation.period_start,item.period_start)||!sameTime(observation.period_end,item.period_end)||!sameTime(observation.available_at,item.available_at)||!equal(numberDecimal(observation.value),item.value)) fail();
        original.add(Number(item.report_observation_index));
      } else if(item.filing_accession===null) fail();
      const key=[item.metric,item.unit,item.currency,instant(item.period_start),instant(item.period_end),item.source.source_id,item.source.snapshot_id].join('|');
      if(factKeys.has(key)) fail();factKeys.add(key);
      evidence.push(item as unknown as AiHistoryFact);
    } else if(item.kind==='comparison') {
      keys(item,['kind','index','metric','previous_index','current_index','delta_value','delta_percent','comparison_reason']);
      if(!Number.isInteger(item.previous_index)||!Number.isInteger(item.current_index)) fail();
      const previous=evidence[Number(item.previous_index)], current=evidence[Number(item.current_index)];
      if(!previous||!current||previous.kind!=='fact'||current.kind!=='fact'||previous.index===current.index||previous.metric!==item.metric||current.metric!==item.metric||previous.unit!=='currency'||current.unit!=='currency'||previous.currency!=='USD'||current.currency!=='USD'||!sameSource(previous.source,current.source)||previous.filing_accession===null||previous.filing_accession!==current.filing_accession) fail();
      const comparisonKey=item.previous_index+':'+item.current_index;
      if(comparisonKeys.has(comparisonKey)) fail();comparisonKeys.add(comparisonKey);
      const day=86400000000n;
      const calendarDay=(raw:string)=>{const stamp=instant(raw),days=stamp/day;return stamp<0n&&stamp%day!==0n?days-1n:days;};
      const previousStart=calendarDay(previous.period_start),previousEnd=calendarDay(previous.period_end),currentStart=calendarDay(current.period_start),currentEnd=calendarDay(current.period_end);
      const previousLength=previousEnd-previousStart,currentLength=currentEnd-currentStart;
      if(previousEnd>=currentStart||previousEnd>=currentEnd||previousLength<300n||previousLength>400n||currentLength<300n||currentLength>400n) fail();
      const lengthDifference=currentLength-previousLength;
      const comparable=currentStart===previousEnd+1n&&lengthDifference>=-8n&&lengthDifference<=8n;
      if(!comparable) {
        if(item.comparison_reason!=='PERIODS_NOT_COMPARABLE'||item.delta_value!==null||item.delta_percent!==null) fail();
      } else {
        if(!decimal(item.delta_value)) fail();
        const scale=Math.max(places(previous.value),places(current.value),places(item.delta_value));
        const baseline=scaled(previous.value,scale),delta=scaled(current.value,scale)-baseline;
        if(scaled(item.delta_value,scale)!==delta) fail();
        if(baseline<=0n) {
          if(item.comparison_reason!=='NON_POSITIVE_BASE'||item.delta_percent!==null) fail();
        } else if(item.comparison_reason!==null||!decimal(item.delta_percent)||! /^-?(?:0|[1-9][0-9]*)\.[0-9]{6}$/.test(item.delta_percent)||scaled(item.delta_percent,6)!==expectedPercent(delta,baseline)) fail();
      }
      evidence.push(item as unknown as AiHistoryComparison);
    } else fail();
  }
  const required=report.input.observations.flatMap((observation,index)=>object(observation)&&observation.status==='available'?[index]:[]);
  if(required.length!==original.size||required.some(index=>!original.has(index))) fail();
}

/** Python canonical_sha256-compatible JSON for the fixed, bounded evidence schema. */
export function canonicalContextJson(value:AiHistoryContext):string {
  const {context_sha256:_,...content}=value;
  const sort=(item:unknown):unknown => Array.isArray(item)?item.map(sort):object(item)?Object.fromEntries(Object.keys(item).sort().map(key=>[key,sort(item[key])])):item;
  return JSON.stringify(sort(content));
}
export async function verifyAiHistoryContextHash(value:AiHistoryContext):Promise<void> {
  const bytes=new TextEncoder().encode(canonicalContextJson(value));
  if(bytes.length>256*1024) fail();
  const digest=await crypto.subtle.digest('SHA-256',bytes);
  const actual=Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');
  if(actual!==value.context_sha256) fail();
}
export function assertAiHistoryNarrative(value:unknown,context:AiHistoryContext):asserts value is AiHistoryNarrative {
  if(!object(value)) fail();
  keys(value,['summary','strengths','risks','questions','limitations']);
  for(const name of ['summary','strengths','risks','questions'] as const) {
    const claims=value[name];
    if(!Array.isArray(claims)||claims.length>6||(name==='summary'&&claims.length===0)) fail();
    for(const claim of claims) {
      if(!object(claim)) fail();
      keys(claim,['kind','text','evidence_indexes','direction']);
      if(!text(claim.text,1200)||/\d|https?:\/\/|<[^>]*>|\b(?:kupuj|kup|sprzedaj|buy|sell)\b/i.test(claim.text)||!Array.isArray(claim.evidence_indexes)||claim.evidence_indexes.length<1||claim.evidence_indexes.length>20||new Set(claim.evidence_indexes).size!==claim.evidence_indexes.length||claim.evidence_indexes.some(index=>!Number.isInteger(index)||!context.evidence[Number(index)])) fail();
      if(name==='questions'?(claim.kind!=='question'):(claim.kind!=='state'&&claim.kind!=='trend')) fail();
      if(claim.kind==='trend') {
        const comparison=context.evidence[Number(claim.evidence_indexes[0])];
        if(claim.evidence_indexes.length!==1||comparison.kind!=='comparison'||comparison.delta_value===null||comparison.comparison_reason==='PERIODS_NOT_COMPARABLE') fail();
        const delta=scaled(comparison.delta_value,places(comparison.delta_value));
        if(claim.direction!==(delta>0n?'increase':delta<0n?'decrease':'unchanged')) fail();
      } else if(claim.direction!==null||(claim.kind==='state'&&claim.evidence_indexes.some(index=>context.evidence[Number(index)].kind!=='fact'))) fail();
    }
  }
  if(!Array.isArray(value.limitations)||value.limitations.length<1||value.limitations.length>12||value.limitations.some(item=>!text(item,1200)||/\d|https?:\/\/|<[^>]*>|\b(?:kupuj|kup|sprzedaj|buy|sell)\b/i.test(item))) fail();
}

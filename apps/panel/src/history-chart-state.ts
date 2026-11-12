export type ChartPoint={period_start:string;period_end:string;value:string|null;reason?:string|null};
export type ChartSeries={id:string;label:string;unit:string;points:ChartPoint[]};
export type ChartMark=ChartPoint&{index:number;x:number;y:number;value:string};
export type HistoryChartLayout={width:number;height:number;left:number;right:number;top:number;bottom:number;zeroY:number;marks:ChartMark[];segments:ChartMark[][];precisionLimited:boolean};
const decimal=/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;
function day(value:unknown):number|null {
  if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value)||value.startsWith('0000'))return null;
  const parsed=Date.parse(value+'T00:00:00Z');
  return Number.isFinite(parsed)&&new Date(parsed).toISOString().slice(0,10)===value?parsed/86400000:null;
}
const places=(value:string)=>value.split('.')[1]?.length??0;
function scaled(value:string,scale:number):bigint {
  const [whole,fraction='']=value.replace(/^-/,'').split('.');
  const n=BigInt(whole+fraction.padEnd(scale,'0'));return value.startsWith('-')?-n:n;
}
/** Only geometry is approximate. All displayed values retain the original decimals. */
export function buildHistoryChart(points:ChartPoint[]):HistoryChartLayout|null {
  if(!Array.isArray(points)||points.length>3)return null;
  const dates:number[]=[];let prior=-Infinity;
  for(const point of points){
    if(!point||typeof point!=='object')return null;
    const start=day(point.period_start),end=day(point.period_end);
    if(start===null||end===null||start>end||end<=prior)return null;
    if(point.value!==null&&(typeof point.value!=='string'||point.value.length>128||!decimal.test(point.value)))return null;
    if(point.reason!==undefined&&point.reason!==null&&(typeof point.reason!=='string'||point.reason.length>2000))return null;
    dates.push(end);prior=end;
  }
  const width=640,height=240,left=48,right=616,top=24,bottom=192;
  const available=points.filter((p):p is ChartPoint&{value:string}=>p.value!==null);
  const scale=Math.max(0,...available.map(p=>places(p.value)));
  const values=available.map(p=>scaled(p.value,scale));
  let min=0n,max=0n;for(const value of values){if(value<min)min=value;if(value>max)max=value;}
  if(min===max){min=-1n;max=1n;}
  const fraction=(n:bigint,d:bigint)=>Number(n*1000000000000n/d)/1000000000000;
  const y=(n:bigint)=>bottom-fraction(n-min,max-min)*(bottom-top);
  const zeroY=y(0n),marks:ChartMark[]=[],segments:ChartMark[][]=[];let segment:ChartMark[]=[];
  const finish=()=>{if(segment.length)segments.push(segment);segment=[];};
  for(const [index,point] of points.entries()){
    if(point.value===null){finish();continue;}
    if(index){const previous=points[index-1],previousStart=day(previous.period_start)!;const currentStart=day(point.period_start)!;if(currentStart!==dates[index-1]+1||Math.abs((dates[index]-currentStart)-(dates[index-1]-previousStart))>8)finish();}
    const x=points.length===1?(left+right)/2:left+(dates[index]-dates[0])/(dates.at(-1)!-dates[0])*(right-left);
    const mark={...point,value:point.value,index,x,y:y(scaled(point.value,scale))};
    if(!Number.isFinite(mark.x)||!Number.isFinite(mark.y)||mark.x<left||mark.x>right||mark.y<top||mark.y>bottom)return null;
    marks.push(mark);segment.push(mark);
  }
  finish();
  const precisionLimited=marks.some((mark,index)=>marks.slice(0,index).some(other=>scaled(mark.value,scale)!==scaled(other.value,scale)&&Math.abs(mark.y-other.y)<1));
  return {width,height,left,right,top,bottom,zeroY,marks,segments,precisionLimited};
}

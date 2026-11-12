import {useId,useState} from 'react';
import {formatHistoryDecimal} from './financial-history-state';
import {observationPeriod} from './report-display';
import {buildHistoryChart} from './history-chart-state';
import type {ChartSeries} from './history-chart-state';

export function HistoryChart({series,title}:{series:ChartSeries[];title:string}){
  const id=useId(),[selected,setSelected]=useState('');
  const active=series.find(item=>item.id===selected)??series[0];
  return <div className="source"><h3>{title}</h3>{active?<><label htmlFor={id}>Metryka wykresu</label><select id={id} value={active.id} onChange={event=>setSelected(event.target.value)}>{series.map(item=><option key={item.id} value={item.id}>{item.label}</option>)}</select><ChartView key={JSON.stringify([active.id,active.points])} series={active}/></>:<p>Brak danych do wykresu.</p>}</div>;
}
function ChartView({series}:{series:ChartSeries}){
  const id=useId(),[selected,setSelected]=useState<number|null>(null),layout=buildHistoryChart(series.points);
  if(!layout)return <p>Nie można bezpiecznie narysować tych okresów. Sprawdź tabelę i źródła.</p>;
  if(!layout.marks.length)return <p>Brak dostępnych wartości do wykresu. Braki nie są zerami; powody znajdziesz w tabeli.</p>;
  const mark=layout.marks.find(item=>item.index===selected);
  const label=(value:string,start:string,end:string)=>series.label+': '+formatHistoryDecimal(value)+' '+series.unit+' · '+observationPeriod(start+'T00:00:00Z',end+'T00:00:00Z');
  return <><p>Jednostka: {series.unit}. Oś pozioma pokazuje datę końca okresu. Wybierz punkt myszą lub klawiszem Tab; Enter i spacja również pokazują szczegóły.</p><svg role="group" aria-labelledby={id+'-title'} aria-describedby={id+'-desc'} viewBox={'0 0 '+layout.width+' '+layout.height} style={{width:'100%',maxWidth:800,height:'auto',display:'block'}}>
    <title id={id+'-title'}>{series.label} — dane historyczne</title><desc id={id+'-desc'}>Linia łączy tylko porównywalne kolejne okresy. Braki przerywają linię. Oś pionowa obejmuje zero. Dokładne wartości i źródła są w tabeli.</desc>
    <line x1={layout.left} y1={layout.zeroY} x2={layout.right} y2={layout.zeroY} stroke="currentColor" strokeOpacity="0.5"/>
    <text x={layout.left-10} y={layout.zeroY+4} textAnchor="end" fill="currentColor" fontSize="12">0</text>
    {layout.segments.filter(segment=>segment.length>1).map((segment,index)=><polyline key={index} points={segment.map(point=>point.x+','+point.y).join(' ')} fill="none" stroke="currentColor" strokeWidth="2"/>)}
    {layout.marks.map(point=><g key={point.index}><circle cx={point.x} cy={point.y} r={point.index===selected?7:5} fill="currentColor" stroke="currentColor" strokeWidth="2" role="button" tabIndex={0} aria-label={label(point.value,point.period_start,point.period_end)} aria-pressed={point.index===selected} onClick={()=>setSelected(point.index)} onFocus={()=>setSelected(point.index)} onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();setSelected(point.index);}}}><title>{label(point.value,point.period_start,point.period_end)}</title></circle></g>)}
    {series.points.map((point,index)=>{const date=Date.parse(point.period_end+'T00:00:00Z'),first=Date.parse(series.points[0].period_end+'T00:00:00Z'),last=Date.parse(series.points.at(-1)!.period_end+'T00:00:00Z');const x=series.points.length===1?(layout.left+layout.right)/2:layout.left+(date-first)/(last-first)*(layout.right-layout.left);return <text key={index} x={x} y={layout.bottom+25} textAnchor={index===0?'start':index===series.points.length-1?'end':'middle'} fill="currentColor" fontSize="12">{point.period_end}</text>;})}
  </svg>{mark?<p role="status"><strong>{label(mark.value,mark.period_start,mark.period_end)}</strong></p>:<p>Wybierz punkt, aby zobaczyć dokładną wartość i pełny okres.</p>}{series.points.some(point=>point.value===null)&&<p>W szeregu są braki. Nie zastępujemy ich zerem i nie łączymy linii przez brakujący okres.</p>}{layout.precisionLimited&&<p>Niektóre różnice są zbyt małe do rozróżnienia w skali wykresu. Sprawdź dokładne wartości w tabeli.</p>}<p>Linia łączy tylko porównywalne kolejne okresy. Dane porównawcze mogą zawierać przekształcenia. Wykres nie jest kursem, prognozą ani odtworzeniem wiedzy inwestora w dawnym roku.</p></>;
}

import {useEffect,useState} from 'react';
import {HistoryChart} from './history-chart';
import type {components} from './schema';
import {metricLabels,observationPeriod} from './report-display';
import {formatHistoryDecimal} from './financial-history-state';
import {assertFinancialRatios,ratioExplanation,ratioFormulas,ratioLabels} from './financial-ratios-state';
import type {FinancialRatiosData} from './financial-ratios-state';
type Report=components['schemas']['ReportRevision'];
const date=(value:string)=>new Intl.DateTimeFormat('pl-PL',{dateStyle:'medium',timeStyle:'short',timeZone:'Europe/Warsaw'}).format(new Date(value));
export function FinancialRatios({report}:{report:Report}) {
  const identity=report.report_id+':'+report.revision+':'+report.checksum;
  const [retry,setRetry]=useState(0),[state,setState]=useState<{identity:string;data?:FinancialRatiosData;error?:string}>({identity:''});
  useEffect(()=>{
    const abort=new AbortController();setState({identity});
    const timer=setTimeout(()=>{if(!abort.signal.aborted){setState({identity,error:'Odczyt wskaźników trwa zbyt długo. Możesz odświeżyć odczyt.'});abort.abort();}},15000);
    fetch('/v1/panel/reports/'+encodeURIComponent(report.report_id)+'/'+report.revision+'/financial-ratios',{signal:abort.signal,cache:'no-store',headers:{Accept:'application/json'}}).then(async response=>{
      if(!response.ok)throw Error(response.status===422?'Wskaźniki wymagają rzeczywistego raportu z archiwum SEC.':response.status===503?'Archiwum jest chwilowo niedostępne.':'Nie udało się odczytać wskaźników ('+response.status+').');
      const value:unknown=await response.json();assertFinancialRatios(value,report);if(!abort.signal.aborted)setState({identity,data:value});
    }).catch(error=>{if(!abort.signal.aborted)setState({identity,error:error instanceof TypeError?'Nie można połączyć się z lokalnym API.':error instanceof Error?error.message:'Nie udało się odczytać wskaźników.'});}).finally(()=>clearTimeout(timer));
    return ()=>{clearTimeout(timer);abort.abort();};
  },[identity,retry]);
  const current=state.identity===identity?state:undefined;
  return <section aria-labelledby="financial-ratios-title"><h2 id="financial-ratios-title">Rentowność i przepływy</h2>
    <p>Wskaźniki obliczone z archiwum bez uruchamiania AI. Łączymy wyłącznie zgodne okresy i to samo sprawozdanie. Nie oceniają wyceny, płynności ani atrakcyjności inwestycji.</p>
    <p>Przepływy operacyjne minus nakłady to ograniczone przybliżenie wolnych przepływów, a nie pełny przepływ dla właścicieli.</p>
    <button onClick={()=>setRetry(n=>n+1)}>Odśwież wskaźniki</button>
    {!current?.data&&!current?.error&&<p role="status">Wczytywanie wskaźników…</p>}{current?.error&&<p role="alert">{current.error}</p>}
    {current?.data&&<><HistoryChart title="Wykres wskaźników" series={(Object.keys(ratioLabels) as (keyof typeof ratioLabels)[]).map(metric=>({id:metric,label:ratioLabels[metric],unit:'%',points:current.data!.ratios.filter(point=>point.metric===metric).map(point=>({period_start:point.period_start,period_end:point.period_end,value:point.value_percent,reason:ratioExplanation(point.reason)}))}))}/>{current.data.ratios.length===0?<p>Brak rocznych okresów do obliczenia wskaźników.</p>:<div style={{overflowX:'auto'}}><table><caption>Udział w przychodach; dokładne wartości procentowe i dowody obliczenia.</caption><thead><tr><th scope="col">Okres</th><th scope="col">Wskaźnik</th><th scope="col">Wartość</th><th scope="col">Podstawa</th></tr></thead><tbody>{current.data.ratios.map(point=><tr key={point.period_start+point.period_end+point.metric}>
      <th scope="row">{observationPeriod(point.period_start+'T00:00:00Z',point.period_end+'T00:00:00Z')}</th><td>{ratioLabels[point.metric]}</td><td>{point.status==='available'&&point.value_percent!==null?formatHistoryDecimal(point.value_percent)+'%':<>Nie wyliczono<small>{ratioExplanation(point.reason)}</small></>}</td><td><details><summary>Sprawdź obliczenie</summary><p>{ratioFormulas[point.metric]}</p>{point.operands.map(operand=>{const series=current.data!.history.series.find(s=>s.metric===operand.metric)!;return <p key={operand.metric}><strong>{metricLabels[operand.metric]??operand.metric}: {formatHistoryDecimal(operand.value)} USD</strong><br/>Sprawozdanie: {series.filing_accession??'Nieustalone'}<br/>Dostępne od {date(series.available_at)} · <a href={series.source_url} target="_blank" rel="noreferrer">Źródło SEC ↗</a><br/>SHA-256: <code>{operand.source_sha256}</code></p>;})}{point.available_at&&<p>Wszystkie składniki dostępne od {date(point.available_at)}.</p>}{point.reason&&<p>Kod: {point.reason}</p>}</details></td>
    </tr>)}</tbody></table></div>}<ul>{current.data.limitations.map((item,index)=><li key={index}>{item}</li>)}</ul></>}
  </section>;
}

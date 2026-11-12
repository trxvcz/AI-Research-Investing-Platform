import {useEffect,useState} from 'react';
import {HistoryChart} from './history-chart';
import type {components} from './schema';
import {metricLabels,observationPeriod} from './report-display';
import {assertFinancialHistory,comparisonExplanation,formatHistoryDecimal} from './financial-history-state';
import type {FinancialHistoryData} from './financial-history-state';

type Report=components['schemas']['ReportRevision'];
const date=(value:string)=>new Intl.DateTimeFormat('pl-PL',{dateStyle:'medium',timeStyle:'short',timeZone:'Europe/Warsaw'}).format(new Date(value));

export function FinancialHistory({report}:{report:Report}) {
  const identity=report.report_id+':'+report.revision+':'+report.checksum;
  const [retry,setRetry]=useState(0);
  const [state,setState]=useState<{identity:string;data?:FinancialHistoryData;error?:string}>({identity:''});
  useEffect(()=>{
    const abort=new AbortController();
    setState({identity});
    const timer=setTimeout(()=>{
      if(!abort.signal.aborted) {
        setState({identity,error:'Odczyt danych porównawczych trwa zbyt długo. Możesz odświeżyć odczyt.'});
        abort.abort();
      }
    },15000);
    fetch('/v1/panel/reports/'+encodeURIComponent(report.report_id)+'/'+report.revision+'/financial-history',{signal:abort.signal,cache:'no-store',headers:{Accept:'application/json'}}).then(async response=>{
      if(!response.ok) throw Error(response.status===422?'Dane porównawcze są dostępne dla rzeczywistych raportów opartych na archiwum SEC.':response.status===503?'Archiwum danych jest chwilowo niedostępne.':'Nie udało się odczytać danych porównawczych ('+response.status+').');
      const value:unknown=await response.json();
      assertFinancialHistory(value,report);
      if(!abort.signal.aborted) setState({identity,data:value});
    }).catch(error=>{
      if(!abort.signal.aborted) setState({identity,error:error instanceof TypeError?'Nie można połączyć się z lokalnym API.':error instanceof Error?error.message:'Nie udało się odczytać historii.'});
    }).finally(()=>clearTimeout(timer));
    return ()=>{clearTimeout(timer);abort.abort();};
  },[identity,retry]);
  const current=state.identity===identity?state:undefined;
  return <section aria-labelledby="financial-history-title">
    <h2 id="financial-history-title">Wyniki na przestrzeni lat</h2>
    <p>Dane porównawcze z tego samego sprawozdania; mogą zawierać przekształcenia. To nie jest odtworzenie wiedzy inwestora w dawnym roku.</p>
    <p>Zmiany obliczamy z archiwum, bez uruchamiania modelu. Nowe analizy AI z historią korzystają z przypisanych okresów porównawczych; wcześniejsze analizy zachowują swój pierwotny zakres.</p>
    <button onClick={()=>setRetry(value=>value+1)}>Odśwież dane porównawcze</button>
    {!current?.data&&!current?.error&&<p role="status">Wczytywanie okresów porównawczych…</p>}
    {current?.error&&<p role="alert">{current.error}</p>}
    {current?.data&&<>
      <HistoryChart title="Wykres wyników rocznych" series={current.data.series.map(series=>({id:series.metric,label:metricLabels[series.metric]??series.metric,unit:series.currency,points:series.points.map(point=>({period_start:point.period_start,period_end:point.period_end,value:point.value}))}))}/>
      {current.data.series.length===0&&<p>Raport nie zawiera obsługiwanych rocznych danych do porównania.</p>}
      {current.data.series.map(series=><article className="source" key={series.metric}>
        <h3>{metricLabels[series.metric]??series.metric}</h3>
        {series.status!=='available'&&<p>{series.status==='unavailable'?'Nie można bezpiecznie utworzyć tej serii.':'Archiwum udostępnia mniej niż trzy okresy tej serii.'} {series.reason&&<small>Kod: {series.reason}</small>}</p>}
        {series.points.length>0&&<div style={{overflowX:'auto'}}><table><caption>Wartości w USD; zmiana względem poprzedniego okresu w tabeli.</caption><thead><tr><th scope="col">Okres</th><th scope="col">Wartość</th><th scope="col">Zmiana wartości</th><th scope="col">Zmiana r/r</th></tr></thead><tbody>{series.points.map(point=><tr key={point.period_end}>
          <th scope="row">{observationPeriod(point.period_start+'T00:00:00Z',point.period_end+'T00:00:00Z')}</th>
          <td>{formatHistoryDecimal(point.value)}</td>
          <td>{point.delta_value===null?'Nie wyliczono':formatHistoryDecimal(point.delta_value)}</td>
          <td>{point.delta_percent===null?'Nie wyliczono':formatHistoryDecimal(point.delta_percent)+'%'}{point.comparison_reason&&<small>{comparisonExplanation(point.comparison_reason)}</small>}</td>
        </tr>)}</tbody></table></div>}
        <p>Dostępność użytego archiwum: {date(series.available_at)}. <a href={series.source_url} target="_blank" rel="noreferrer">Źródło SEC ↗</a></p>
        <details><summary>Pochodzenie okresów</summary><p>Sprawozdanie: {series.filing_accession??'Nie wybrano jednoznacznego sprawozdania'}. {series.points.length>0&&'Data złożenia: '+series.points[0].filing_date+'.'}</p><p>SHA-256 źródła: <code>{series.source_sha256}</code></p></details>
      </article>)}
      <ul>{current.data.limitations.map((limitation,index)=><li key={index}>{limitation==='Historia nie jest jeszcze wejściem zapisanej analizy AI. Zmiany obliczono deterministycznie na danych archiwum SEC.'?'Zmiany obliczono deterministycznie na danych archiwum SEC. Tabela nie zmienia wcześniejszych analiz AI; analizy z historią mają własne, zapisane dowody.':limitation}</li>)}</ul>
    </>}
  </section>;
}

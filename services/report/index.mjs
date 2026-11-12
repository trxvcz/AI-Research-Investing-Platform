import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
export async function save(report,closes,base){
 const dir=path.join(base,report.id); await mkdir(base,{recursive:true}); await mkdir(dir);
 const pts=closes.map((v,i)=>(40+i*65)+','+(160-(v-95)*8)).join(' ');
 await writeFile(path.join(dir,'chart.svg'),'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 210"><rect width="560" height="210" fill="white"/><text x="20" y="20">SYNTHETIC DEMO — USD, sequence index</text><path d="M40 40V170H530" fill="none" stroke="black"/><text x="5" y="45">110</text><text x="5" y="165">95</text><text x="40" y="195">0</text><text x="490" y="195">7</text><polyline points="'+pts+'" fill="none" stroke="blue"/></svg>');
 await writeFile(path.join(dir,'report.json'),JSON.stringify(report,null,2));
 const safe=JSON.stringify(report,null,2).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
 await writeFile(path.join(dir,'report.html'),'<!doctype html><html lang="en"><meta charset="utf-8"><title>AlphaSense demo</title><h1>Synthetic demo — not investment evidence</h1><img alt="Synthetic prices in USD by sequence index" src="chart.svg"><pre>'+safe+'</pre></html>');
 return dir;
}


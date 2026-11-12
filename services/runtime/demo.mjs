import {randomUUID,createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {loadDemo,validateData} from '../data/index.mjs';
import {analyze as fundamental} from '../fundamental/index.mjs';
import {analyze as technical} from '../technical/index.mjs';
import {save} from '../report/index.mjs';
export async function run(base=process.env.ARTIFACT_DIR||'artifacts',type='equity'){
 const d=loadDemo(type);validateData(d);const trace=['data'];
 const f=fundamental(d);trace.push('fundamental');const t=technical(d);trace.push('technical','report','reviewer');
 const r={id:randomUUID(),parent_id:null,created_at:new Date().toISOString(),status:'demo',input_hash:createHash('sha256').update(JSON.stringify(d)).digest('hex'),code_version:'starter-0.1.0',analysis:{asset_id:d.asset_id,asset_type:d.asset_type,as_of:d.as_of,fundamental:f,technical:t,sources:[d.source_id],status:'demo'},trace,charts:['chart.svg'],warnings:['Synthetic data only; no investment performance','Reviewer checks structure only; independent domain review pending M3']};
 if(!Number.isFinite(t.sma3))throw Error('review rejected');await save(r,d.closes,base);return r;
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href) console.log(JSON.stringify(await run(),null,2));


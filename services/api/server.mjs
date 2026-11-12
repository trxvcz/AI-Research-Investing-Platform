import http from 'node:http';import {readFile,readdir,access} from 'node:fs/promises';import path from 'node:path';
const base=path.resolve(process.env.ARTIFACT_DIR||'artifacts'),web=path.resolve('apps/frontend');
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript','.json':'application/json','.webmanifest':'application/manifest+json','.svg':'image/svg+xml'};
http.createServer(async(req,res)=>{try{
 res.setHeader('X-Content-Type-Options','nosniff');res.setHeader('Cache-Control','no-store');res.setHeader('Content-Security-Policy',"default-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'");
 if(req.method!=='GET'){res.writeHead(405).end();return;}
 const p=new URL(req.url,'http://localhost').pathname;
 if(p==='/health'||p==='/ready'){await access(web);res.setHeader('Content-Type','application/json');res.end(JSON.stringify({status:'ok',mode:'demo'}));return;}
 if(p==='/reports'){const ids=(await readdir(base).catch(e=>e.code==='ENOENT'?[]:Promise.reject(e))).filter(x=>/^[a-f0-9-]{36}$/.test(x));res.setHeader('Content-Type','application/json');res.end(JSON.stringify(ids));return;}
 let file;
 const match=p.match(/^\/reports\/([a-f0-9-]{36})\/(report\.json|report\.html|chart\.svg)$/);
 if(match)file=path.join(base,match[1],match[2]);else {const allowed={'/':'index.html','/app.js':'app.js','/sw.js':'sw.js','/manifest.webmanifest':'manifest.webmanifest','/icon.svg':'icon.svg'};if(!allowed[p]){res.writeHead(404).end();return;}file=path.join(web,allowed[p]);}
 const body=await readFile(file);res.setHeader('Content-Type',types[path.extname(file)]||'application/octet-stream');res.end(body);
 }catch(e){res.writeHead(e.code==='ENOENT'?404:500).end('Unavailable');}}).listen(Number(process.env.PORT||8080),process.env.HOST||'127.0.0.1');


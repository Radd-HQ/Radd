/** Actual backend declarations, host Audit page and Milestones remote navigation. */
import assert from 'node:assert/strict';
import http from 'node:http';
import {execFileSync} from 'node:child_process';
import {readFileSync,existsSync,statSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import path from 'node:path';
import {openBrowser} from './lib/cdp.mjs';
import { CORE_PLUGINS } from "./lib/core-plugins.mjs";
const root=new URL('../../',import.meta.url).pathname,dist=path.join(root,'web/dist');
const evidence=JSON.parse(execFileSync(path.join(root,'server/.venv/bin/python'),['-c',`
import json,importlib
from pathlib import Path
from radd.kernel import KernelRegistries
from radd.kernel.entity_links import resolve_entity_link
expected=json.loads(Path('tests/fixtures/audit-entity-destinations.json').read_text())
r=KernelRegistries()
for owner in sorted({row['owner'] for row in expected}|{'milestones'}):r.register_plugin(importlib.import_module('radd.modules.'+owner).plugin)
rows=[]
for i,original in enumerate(expected+[{'owner':'milestones','entity_type':'milestone'}],1):
 kind=original['entity_type'];refs={'item':{'key':'TEST-7'},'page':{'number':123}};project={'id':'project','key':'TEST','name':'Test'}
 link=resolve_entity_link(kind,'saved',refs=refs,project=project,registry=r)
 rows.append(dict(id=i,at='2026-09-26T00:00:00Z',actor=None,event_type=kind+'.updated',event_label='Entity updated',event_group='Fixture',entity_type=kind,entity_id='saved',entity_label=kind,refs=refs,project=project,automated=False,silent=False,changes=[{'field':'name','from':'Before','to':'After'}],entity_owner=link.owner,entity_url=link.url))
print(json.dumps({'rows':rows,'plugins':[p.name for p in r.plugins.values()]}))
`],{cwd:path.join(root,'server'),encoding:'utf8'}));
let github=true,milestones=true,broken=false,version=1,hold=false,denied=false;
const requests=[],pending=[],aborted=[],writes=[];
const rows=()=>evidence.rows.map(row=>!github&&row.entity_owner==='github'?{...row,entity_url:null,entity_owner:null}:!milestones&&row.entity_owner==='milestones'?{...row,entity_url:null,entity_owner:null}:row);
const server=http.createServer((req,res)=>{
 const p=new URL(req.url,'http://fixture').pathname;
 if(p.startsWith('/plugins/')){if(broken && p.includes("/milestones/")){res.statusCode=404;res.end();return;}const[,,name,...parts]=p.split('/');res.setHeader('content-type','text/javascript');res.end(readFileSync(path.join(root,'server/src/radd/modules',name,'ui/dist',...parts)));return;}
 if(p.startsWith('/api/')){
  res.setHeader('content-type','application/json');
  if(!['GET','HEAD'].includes(req.method)&&!p.endsWith('/preferences'))writes.push({p,method:req.method});
  if(p==='/api/v1/audit'){
   const entry={url:req.url,github,milestones};requests.push(entry);res.on('close',()=>{if(!res.writableEnded)aborted.push(entry);});const snapshot=rows();
   const finish=()=>{res.statusCode=denied?403:200;res.end(JSON.stringify(denied?{detail:'Scope denied'}:snapshot));};if(hold)pending.push(finish);else finish();return;
  }
  let data=[];
  if(p.endsWith('/auth/me'))data={id:'admin',name:'Admin',email:'admin@example.test',instance_role:'admin',global_role:'admin',permissions:['*']};
  else if(p.endsWith('/capabilities'))data={capabilities:[],plugins:[...CORE_PLUGINS,'audit',...evidence.plugins.filter(name=>(name!=='github'||github)&&(name!=='milestones'||milestones))],remotes:[{name:'audit',remote_entry:'/plugins/audit/remoteEntry.js',ui_api_version:'1.11.0'},{name:'items',remote_entry:'/plugins/items/remoteEntry.js',ui_api_version:'1.11.0'},...(milestones?[{name:'milestones',remote_entry:`/plugins/milestones/remoteEntry.js?v=${version}`,ui_api_version:'1.0.0'}]:[])],nav:milestones?[{key:'milestones',plugin:'milestones',label:'Milestones',path:'/milestones',section:'main',requires:[]}]:[],widget_types:[],view_types:[]};
  else if(p==='/api/v1/audit/access')data={allowed:true,instance_wide:true};
  else if(p==='/api/v1/audit/catalog')data={entity_types:evidence.rows.map(row=>({key:row.entity_type,label:row.entity_type})),event_types:[]};
  else if(p==='/api/v1/milestones')data=[{id:'saved',project_id:'project',title:'Owner-linked milestone',description:'Preserved navigation',status:'open',due_on:null}];
  else if(p==='/api/v1/projects')data=[{id:'project',key:'TEST',name:'Test',permissions:['project.manage']}];
  else if(p.endsWith('/summary'))data={total:0,related_count:0,permissions:[]};
  else if(p.includes('notifications'))data={items:[],notifications:[],unread_count:0,total:0};else if(p.includes('preferences'))data={};res.end(JSON.stringify(data));return;
 }
 const f=path.join(dist,p),target=existsSync(f)&&statSync(f).isFile()?f:path.join(dist,'index.html');res.setHeader('content-type',target.endsWith('.js')?'text/javascript':target.endsWith('.css')?'text/css':'text/html');res.end(readFileSync(target));
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let browser;const checks=[];
try{
 browser=await openBrowser({port:18840,profile:await mkdtemp('/tmp/radd-audit-links-'),scale:1});const s=browser.session;
 const ev=code=>s.eval(`(()=>{${code}})()`),until=async(fn,label)=>{for(let i=0;i<250;i++){if(await fn())return;await new Promise(r=>setTimeout(r,40));}throw Error(label+': '+await s.eval('document.body?.innerText')+' '+JSON.stringify(s.consoleErrors));};
 const refresh=()=>s.eval("window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['capabilities']})");
 const nav=()=>s.send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/settings/audit`});
 const selector=kind=>`[data-audit-event="${kind}.updated"]`;
 const linked=kind=>s.eval(`!!document.querySelector(${JSON.stringify(selector(kind)+' a[data-audit-entity-link]')})`);
 const waitRows=()=>until(()=>s.eval('document.querySelectorAll("[data-audit-row]").length===47'),'all original rows and contributed entity');
 const flush=()=>{while(pending.length)pending.shift()();};
 await nav();await waitRows();
 const actual=await s.eval("Array.from(document.querySelectorAll('[data-audit-row]')).map(row=>({kind:row.getAttribute('data-audit-event').replace('.updated',''),href:row.querySelector('[data-audit-entity-link]')?.getAttribute('href')}))");
 for(const entry of evidence.rows){const found=actual.find(row=>row.kind===entry.entity_type);assert.equal(found?.href,entry.entity_url,entry.entity_type);}checks.push('all 46 migrated destinations plus declarative Milestones are exact hrefs from actual backend contracts');
 await s.click(selector('milestone')+' [data-audit-entity-link]');await until(()=>s.eval("document.getElementById('milestone-saved')?.innerText.includes('Owner-linked milestone')"),'actual remote destination');assert.equal(await s.eval('location.hash'),'#milestone-saved');checks.push('contributed entity link opens its actual Milestones bundle and preserves the target fragment');
 await nav();await waitRows();hold=true;await ev("window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['audit']})");await until(()=>pending.length>=1,'in-flight audit read');const before=aborted.length;github=false;await refresh();await until(async()=>!(await linked('github_connection')),'cached github destination withdrawn');await until(()=>aborted.length>before,'old owner generation request aborted');hold=false;flush();await waitRows();assert(!(await linked('github_repo')));assert(await linked('forgejo_connection'));assert(await s.eval(`document.querySelector('${selector('github_connection')}').innerText.includes('Before')`));checks.push('owner withdrawal cancels the older read and removes only its links while retaining history and changes');
 github=true;await refresh();await until(()=>linked('github_connection'),'github fresh restored links');checks.push('re-enable fetches destinations for the current owner set');
 milestones=false;await refresh();await until(async()=>!(await linked('milestone')),'derived destination withdrawn');await waitRows();assert(await linked('page'));milestones=true;version++;await refresh();await until(()=>linked('milestone'),'derived destination restored');checks.push('declarative entity URL follows owner withdrawal and restoration independently of built-in destinations');
 broken=true;version++;await refresh();await until(()=>s.eval("document.querySelectorAll('[data-audit-row]').length===47"),'current rows');await s.click(selector('milestone')+' [data-audit-entity-link]');await until(()=>s.eval("/unavailable|failed|could not be loaded/i.test(document.body?.innerText??'')"),'failed contributed destination reports failure');broken=false;version++;await refresh();await until(()=>s.eval("document.getElementById('milestone-saved')?.innerText.includes('Owner-linked milestone')"),'remote recovery');checks.push('failed destination bundle shows the generic unavailable page and recovers on a new version');
 await nav();await waitRows();denied=true;await ev("window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['audit']})");await until(()=>s.eval("document.body?.innerText.includes('You need admin access')"),'permission refusal');assert.equal(await s.eval("document.querySelectorAll('[data-audit-row]').length"),0);denied=false;await ev("window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['audit']})");await waitRows();checks.push('a denied refresh hides previous rows and destinations instead of displaying stale audit data');
 await s.screenshot('/tmp/radd-audit-entity-links.png');assert.equal(writes.length,0);assert(!s.consoleErrors.some(e=>/Invalid hook|Maximum update depth|not exported/.test(e)));console.log(JSON.stringify({passed:true,checks,requests:requests.length,aborted:aborted.length,destinations:evidence.rows.length}));
}finally{while(pending.length)pending.shift()();if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}

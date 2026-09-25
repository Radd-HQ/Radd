/** Actual Scripts/Monitoring/AI/mail bundles: forms, ownership and live lifecycle. */
import assert from 'node:assert/strict';
import http from 'node:http';
import {readFileSync, existsSync, statSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import path from 'node:path';
import {openBrowser} from './lib/cdp.mjs';
const dist=new URL('../dist/',import.meta.url).pathname;
const enabled=new Set(); const broken=new Set(); const reads=[]; const writes=[];
let rev=1, packages=[], hold='', release, aborted=0, denied=false;
const interpreter={python_version:'3.12',status:'ready',resolved:'3.12.8',log:'Fixture built',built_at:'2026-09-25T12:00:00Z',path:'/managed/python',available:['3.12','3.13'],sdk_source:'radd-sdk',wheelhouses:[],operator_wheelhouse:'/wheels',index_url:'https://mirror.example/simple',offline:true};
const overview={database:{ok:true,postgres_version:'16',size_bytes:1048576,active_connections:4},counts:[{key:'items',label:'Issues',count:42}],workers:[{name:'fixture.worker',description:'Description supplied by owner',registered:true,last_event_id:42,stream_head:42,lag:0,seconds_since_update:300}],workers_in_process:true};
const coverage={enabled:true,items_total:42,items_embedded:30,docs_total:10,docs_embedded:10};
const mail={window_hours:24,failures:1,given_up:1,capped:false,recent:[{at:'2026-09-25T12:00:00Z',recipient:'fixture@example.test',subject:'Fixture message',error:'Relay refused fixture',given_up:true}]};
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,'http://fixture'),p=url.pathname;
 if(p.startsWith('/plugins/')) {
  const [, ,name,...rest]=p.split('/');
  if(broken.has(name)){res.writeHead(404);res.end();return;}
  const file=new URL(`../../server/src/radd/modules/${name}/ui/dist/${rest.join('/')}`,import.meta.url).pathname;
  if(!existsSync(file)){res.writeHead(404);res.end();return;}
  res.setHeader('content-type',file.endsWith('.js')?'text/javascript':'text/css');res.end(readFileSync(file));return;
 }
 if(p.startsWith('/api/')) {
  let data=[];
  if(p.endsWith('/auth/me'))data={id:'admin',name:'Admin',email:'admin@example.test',instance_role:denied?'member':'admin',global_role:denied?'member':'admin',permissions:denied?[]:['*']};
  else if(p.includes('capabilities'))data={capabilities:[],plugins:[...enabled],remotes:[...enabled].map(name=>({name,remote_entry:`/plugins/${name}/remoteEntry.js?v=${rev}`,ui_api_version:'1.3.0'})),nav:[...enabled].filter(x=>['scripts','monitoring'].includes(x)).map(name=>({key:name,plugin:name,label:name==='scripts'?'Scripts':'Monitoring',path:`/settings/${name}`,section:'settings',group:'Server',icon:name==='scripts'?'Terminal':'Activity',order:name==='scripts'?95:115,requires:name==='scripts'?['script.manage']:[],requires_admin:name==='monitoring'})),widget_types:[],view_types:[]};
  else if(/^\/api\/v1\/(scripts|monitoring|ai\/embeddings|mail\/health)/.test(p)) {
   reads.push(p);
   if(denied){res.writeHead(403,{'content-type':'application/json'});res.end(JSON.stringify({detail:'Operator permission required'}));return;}
   if(hold===p){res.on('close',()=>{if(!res.writableEnded)aborted++;});await new Promise(resolve=>{release=resolve;});}
   let body; if(['PUT','POST'].includes(req.method)){let raw='';for await(const chunk of req)raw+=chunk;body=JSON.parse(raw);writes.push({path:p,body});}
   if(p.endsWith('/scripts/interpreter')){if(body)Object.assign(interpreter,body);data=interpreter;}
   else if(p.endsWith('/scripts/interpreter/rebuild')){Object.assign(interpreter,{python_version:body.python_version,status:'ready'});data=interpreter;}
   else if(p.endsWith('/scripts/packages')){if(body)packages.push({id:'pkg',name:'fixture-package',spec:body.spec,resolved_version:'1.0',status:'installed',log:'Installed',created_at:'2026-09-25',installed_at:'2026-09-25'});data=packages;}
   else if(p.endsWith('/scripts/packages/pkg')&&req.method==='DELETE'){packages=[];res.writeHead(204);res.end();return;}
   else if(p.endsWith('/monitoring/overview'))data=overview;
   else if(p.endsWith('/ai/embeddings/coverage'))data=coverage;
   else if(p.endsWith('/mail/health'))data=mail;
  }
  else if(p.endsWith('/projects/summary')||p.endsWith('/page-spaces/summary'))data={total:0,related_count:0,permissions:[]};
  else if(p.includes('notifications'))data={items:[],notifications:[],unread_count:0,total:0};
  else if(p.includes('preferences'))data={};
  res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify(data));return;
 }
 const file=path.join(dist,p),target=existsSync(file)&&statSync(file).isFile()?file:path.join(dist,'index.html');
 res.setHeader('content-type',target.endsWith('.js')?'text/javascript':target.endsWith('.css')?'text/css':'text/html');res.end(readFileSync(target));
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
let browser;
const checks=[];
try{
 browser=await openBrowser({port:18830,profile:await mkdtemp('/tmp/radd-settings-ownership-'),scale:1});
 const s=browser.session,base=`http://127.0.0.1:${server.address().port}`;
 const text=t=>s.eval(`document.body.innerText.includes(${JSON.stringify(t)})`);
 const until=async(p,label)=>{for(let i=0;i<300;i++){if(await p())return;await new Promise(r=>setTimeout(r,40));}throw Error(label+': '+await s.eval('document.body.innerText')+' '+JSON.stringify(s.consoleErrors));};
 const refresh=()=>s.eval(`window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['capabilities']})`);
 const change=async(fn)=>{fn();rev++;await refresh();};
 const field=async(selector,value)=>s.eval(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,${JSON.stringify(value)});el.dispatchEvent(new Event('input',{bubbles:true}));})()`);
 await s.navigate(base+'/settings/scripts');await until(()=>text('This page is unavailable.'),'initially disabled Scripts');assert.equal(reads.length,0);checks.push('initially disabled Scripts makes no requests');
 await change(()=>enabled.add('scripts'));await until(()=>text('Package index'),'Scripts enabled');
 assert(await s.eval(`Array.from(document.querySelectorAll('section[aria-label="Server"] a')).filter(a=>a.textContent==='Scripts').length===1`));
 await until(()=>s.eval(`document.querySelector('[data-scripts-index] input').value==='https://mirror.example/simple'`),'saved index restored');
 await field('[data-scripts-index] input','https://new-mirror.example/simple');await s.click('[data-scripts-index] button',t=>t.trim()==='Save');await until(()=>writes.some(x=>x.body.index_url==='https://new-mirror.example/simple'),'index saved');
 await field('[data-scripts-packages] input','fixture-package>=1');await s.click('[data-scripts-packages] button',t=>t.trim()==='Install');await until(()=>text('fixture-package'),'package saved');
 await s.eval(`document.querySelector('[aria-label="Remove fixture-package"]').click()`);await until(()=>s.eval(`!document.querySelector('[data-package="fixture-package"]')`),'package removed');
 await s.click('[data-scripts-interpreter] button',t=>t.trim()==='Rebuild');await until(()=>writes.some(x=>x.path.endsWith('/rebuild')&&x.body.python_version==='3.12'),'interpreter rebuild');
 assert(await s.eval(`getComputedStyle(document.querySelector('[data-scripts-index]')).paddingTop==='16px'`),'remote layout utilities survive relocation');
 assert(await s.eval(`getComputedStyle(document.querySelector('[data-scripts-index] input')).minWidth==='288px'`),'remote-only utility is emitted');
 await s.screenshot('/tmp/radd-scripts-owned.png');checks.push('Scripts saved settings, install/remove, rebuild, navigation and styles');
 await change(()=>enabled.delete('scripts'));await until(()=>text('This page is unavailable.'),'Scripts withdrawal');const scriptReadCount=reads.length;await new Promise(r=>setTimeout(r,600));assert.equal(reads.length,scriptReadCount);
 await change(()=>enabled.add('scripts'));await until(()=>text('Package index'),'Scripts returns');await until(()=>s.eval(`document.querySelector('[data-scripts-index] input').value==='https://new-mirror.example/simple'`),'saved settings survive');checks.push('Scripts live withdrawal/re-enable preserves saved config');
 await change(()=>enabled.delete('scripts'));
 await s.navigate(base+'/settings/monitoring');await until(()=>text('This page is unavailable.'),'initially disabled Monitoring');assert(!reads.some(x=>x.includes('/monitoring/')));checks.push('initially disabled Monitoring makes no requests');
 await change(()=>enabled.add('monitoring')); await until(()=>text('Description supplied by owner'),'Monitoring enabled');assert(!reads.some(x=>x.includes('/ai/')||x.includes('/mail/health')));checks.push('Monitoring renders worker owner text without querying disabled cards');
 await change(()=>{enabled.add('ai');enabled.add('mailintake');});await until(async()=>await text('Semantic index')&&await text('Relay refused fixture'),'dependent cards enabled');
 assert(await text('Pages embedded'));assert.equal(await s.eval(`Array.from(document.querySelectorAll('.radd-card__title')).filter(e=>e.textContent==='Semantic index').length`),1);
 await s.screenshot('/tmp/radd-monitoring-owned.png');checks.push('AI and mail own actual contributed cards');
 hold='/api/v1/ai/embeddings/coverage';await s.eval(`void window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['ai','monitoring-coverage']})`);
 await until(()=>Boolean(release),'AI query held');await change(()=>enabled.delete('ai'));await until(async()=>!await text('Semantic index'),'AI removed live');await until(()=>aborted>0,'AI request aborted');release();release=undefined;hold='';coverage.items_embedded=41;
 const aiReadCount=reads.filter(x=>x.includes('/ai/')).length;await new Promise(r=>setTimeout(r,5500));assert.equal(reads.filter(x=>x.includes('/ai/')).length,aiReadCount);checks.push('AI withdrawal cancels in-flight query and polling');
 await change(()=>enabled.delete('mailintake'));await until(async()=>!await text('Outbound mail'),'mail removed');
 await change(()=>{enabled.add('ai');enabled.add('mailintake');});await until(async()=>await text('Semantic index')&&await text('Outbound mail'),'cards restored');await until(()=>text('41 / 42'),'fresh coverage after re-enable');checks.push('cards re-enable with fresh data and no duplicate registration');
 await change(()=>enabled.delete('monitoring'));await until(()=>text('This page is unavailable.'),'Monitoring disabled');const count=reads.length;await new Promise(r=>setTimeout(r,5500));assert.equal(reads.length,count);checks.push('Monitoring withdrawal stops every visible card poll');
 broken.add('monitoring');await change(()=>enabled.add('monitoring'));await until(()=>text('This plugin page could not be loaded.'),'Monitoring bundle failure');broken.delete('monitoring');await change(()=>{});await until(()=>text('Description supplied by owner'),'Monitoring recovery');checks.push('actual Monitoring bundle unavailable and recovered');
 await change(()=>{enabled.delete('monitoring');enabled.add('scripts');broken.add('scripts');});await s.navigate(base+'/settings/scripts');await until(()=>text('This plugin page could not be loaded.'),'Scripts bundle failure');broken.delete('scripts');await change(()=>{});await until(()=>text('Package index'),'Scripts recovery');checks.push('actual Scripts bundle unavailable and recovered');
 denied=true;await s.navigate(base+'/settings/scripts');await until(()=>text('Operator permission required'),'permission error visible');assert(!await s.eval(`document.querySelector('[data-scripts-index]')!==null`));checks.push('permission denial hides actionable forms');
 console.log(JSON.stringify({passed:true,checks}));
}finally{release?.();if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}

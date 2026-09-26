/** VCS/provider settings ownership with real bundles and isolated mock writes. */
import assert from 'node:assert/strict';
import http from 'node:http';
import {readFileSync,existsSync,statSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
import {openBrowser} from './lib/cdp.mjs';
const root=new URL('../../',import.meta.url).pathname, dist=path.join(root,'web/dist');
const fixtures=JSON.parse(execFileSync(path.join(root,'server/.venv/bin/python'),[path.join(root,'web/scripts/automation-ui-fixture.py')],{cwd:path.join(root,'server'),encoding:'utf8'}));
const enabled=new Set(['vcs','projects','auth','timelogging','automations','audit']), remotes=new Set(['vcs','projects','auth','timelogging','github','forgejo','gitlab','automations','audit']);
const broken=new Set(), versions={}, requests=[], writes=[], aborted=[], pending=[], checks=[];
let hold=null, deny=null, admin=true;
const project={id:'project-1',key:'TEST',name:'Sample project',permissions:['project.manage'],created_at:'2026-09-01T00:00:00Z'};
const connections=Object.fromEntries(['github','forgejo','gitlab'].map(owner=>[owner,{id:owner+'-1',name:owner+' host',base_url:'https://code.example.test',active:true,verify_ssl:true,has_token:true,has_secret:true,repo_count:1,created_at:'2026-09-01T00:00:00Z'}]));
const repos=Object.fromEntries(['github','forgejo','gitlab'].map(owner=>[owner,{id:owner+'-repo',connection_id:owner+'-1',full_name:owner+'/demo',project_id:'project-1',time_category_id:'category-1',mirror_time:false,move_on_merge:false,publish_on_release:false,enabled:true,link_all_projects:true,default_branch:'main',last_backfill_at:null,created_at:'2026-09-01T00:00:00Z'}]));
let mapped=[], unmatched=[{external_username:'developer',external_email:'',pending_entries:1,pending_seconds:3600,pending_duration:"1h",last_seen_at:null}];
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,'http://fixture'),p=url.pathname;
 if(p.startsWith('/plugins/')){const[,,name,...parts]=p.split('/'),file=path.join(root,'server/src/radd/modules',name,'ui/dist',...parts);if(broken.has(name)||!existsSync(file)){res.statusCode=404;res.end();return;}res.setHeader('content-type',p.endsWith('.css')?'text/css':'text/javascript');res.end(readFileSync(file));return;}
 if(p.startsWith('/api/')){
  let raw='';for await(const chunk of req)raw+=chunk;const body=raw?JSON.parse(raw):null;
  const request={p,method:req.method,body};requests.push(request);if(req.method!=='GET'&&!p.endsWith('/preferences'))writes.push(request);
  res.on('close',()=>{if(!res.writableEnded)aborted.push(request);});res.setHeader('content-type','application/json');
  let data=[],status=200;
  if(p.endsWith('/auth/me'))data={id:'admin',name:'Admin',email:'admin@example.test',instance_role:admin?'admin':'member',global_role:admin?'admin':'member',permissions:[]};
  else if(p.endsWith('/capabilities'))data={capabilities:[],plugins:[...enabled],remotes:[...enabled].filter(name=>remotes.has(name)).map(name=>({name,remote_entry:`/plugins/${name}/remoteEntry.js?v=${versions[name]??1}`,ui_api_version:'1.13.0'})),nav:enabled.has('vcs')?[{plugin:'vcs',key:'vcs',icon:'GitBranch',path:'/settings/vcs',section:'settings',group:'Issues',label:'Version control',requires:['global.manage']}]:[],widget_types:[],view_types:[]};
  else if(p==='/api/v1/automations/catalog')data=fixtures.catalog;
  else if(p==='/api/v1/automations/templates')data=fixtures.templates;
  else if(p==='/api/v1/audit/access')data={allowed:true};
  else if(p.endsWith('/instance'))data={timelog_hours_per_day:7,timelog_days_per_week:5};
  else if(p.endsWith('/work-categories'))data=[{id:'category-1',name:'Development',archived:false}];
  else if(p==='/api/v1/projects'){data=[project];res.setHeader('X-Total-Count','1');}
  else if(p==='/api/v1/projects/project-1'||p==='/api/v1/projects/by-key/TEST')data=project;
  else if(p.includes('/people')||p==='/api/v1/users/directory'){data=[{id:'person-1',name:'Mapped person',email:'person@example.test',instance_role:'member',active:true}];res.setHeader('X-Total-Count','1');}
  else if(p.endsWith('/unmatched/replay')){mapped=[{id:'mapping-1',provider:'github',connection_id:'github-1',external_username:body.external_username,user_id:body.user_id,user_name:'Mapped person',matched_by:'manual'}];unmatched=[];data={replayed:1};}
  else if(p.endsWith('/unmatched'))data=unmatched;
  else if(p.endsWith('/identities'))data=mapped;
  else if(p.startsWith('/api/v1/vcs/identities/')&&req.method==='DELETE'){mapped=[];data=null;}
  else if(/^\/api\/v1\/(github|forgejo|gitlab)\//.test(p)){
   const owner=p.split('/')[3],part=p.split('/')[4],id=p.split('/')[5];
   if(p.endsWith('/test'))data={ok:true,version:'Verified host',detail:''};
   else if(p.endsWith('/backfill'))data={linked:3,branches:1,commits:1,pull_requests:1,unknown_keys:['MISSING-1'],worklogs:{mirrored:1},errors:[]};
   else if(part==='connections'){
    if(req.method==='PATCH')Object.assign(connections[owner],body);
    if(req.method==='POST')Object.assign(connections[owner],{name:body.name,base_url:body.base_url});
    data=id||req.method!=='GET'?connections[owner]:[connections[owner]];
   } else if(part==='repos'){
    if(req.method==='PATCH')Object.assign(repos[owner],body);
    data=id||req.method!=='GET'?repos[owner]:[repos[owner]];
   }
  }
  else if(p.endsWith('/summary'))data={total:1,related_count:0,permissions:[]};
  else if(p.includes('/notifications'))data={items:[],notifications:[],unread_count:0,total:0};
  else if(p.includes('/preferences'))data={};
  if(deny===p){status=403;data={detail:'Access denied to connector data'};}
  const finish=()=>{res.statusCode=status;res.end(JSON.stringify(data));};if(hold===p)pending.push(finish);else finish();return;
 }
 const file=path.join(dist,p),target=existsSync(file)&&statSync(file).isFile()?file:path.join(dist,'index.html');res.setHeader('content-type',target.endsWith('.js')?'text/javascript':target.endsWith('.css')?'text/css':'text/html');res.end(readFileSync(target));
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let browser;
try{
 browser=await openBrowser({port:18843,profile:await mkdtemp('/tmp/radd-vcs-settings-'),scale:1});const s=browser.session;
 const body=()=>s.eval('document.body?.innerText??""');
 const until=async(fn,label)=>{for(let i=0;i<250;i++){if(await fn())return;await new Promise(r=>setTimeout(r,40));}throw Error(label+': '+await body()+' '+JSON.stringify(s.consoleErrors));};
 const has=text=>s.eval(`document.body?.innerText.includes(${JSON.stringify(text)})`),exists=selector=>s.eval(`!!document.querySelector(${JSON.stringify(selector)})`);
 const refresh=()=>s.eval("window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['capabilities']})");
 const invalidate=()=>s.eval("void window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['vcs']})");
 const nav=p=>s.navigate(`http://127.0.0.1:${server.address().port}${p}`);
 const button=label=>s.click('button',new Function('text',`return text.trim()===${JSON.stringify(label)}`));
 const fill=async(label,value)=>{const selector=await s.eval(`(()=>{const label=[...document.querySelectorAll('label')].find(el=>el.textContent.trim()===${JSON.stringify(label)});return label?.htmlFor?'#'+CSS.escape(label.htmlFor):null;})()`);assert(selector,label+' input');await s.click(selector);await s.eval(`document.querySelector(${JSON.stringify(selector)}).select()`);await s.send('Input.insertText',{text:value});};
 const flush=()=>{while(pending.length)pending.shift()();};
 await nav('/settings/vcs?host=github');await until(()=>has('No version control connectors are available.'),'empty owner page');assert(!requests.some(r=>/^\/api\/v1\/(github|forgejo|gitlab)\//.test(r.p)));checks.push('initially absent providers contribute no tabs or requests');
 enabled.add('github');enabled.add('forgejo');enabled.add('gitlab');await refresh();await until(()=>has('github/demo'),'Github rendered');assert.equal(await s.eval('document.querySelectorAll("[role=tab]").length'),3);await until(()=>has('TEST · Sample project'),'project resolved');assert(await has('Development'));await until(()=>exists('[data-settings-history] a'),'owned Audit footer');assert.match(await s.eval("document.querySelector('[data-settings-history] a').getAttribute('href')"),/github_connection/);checks.push('real provider bundles contribute three tabs; owner lookups and Audit history receive the selected connector context');
 await button('Edit');await until(()=>has('Save host'),'host form');await fill('Name','Renamed host');await button('Save host');await until(async()=>connections.github.name==='Renamed host'&&!await has('Save host'),'host saved');const saved=writes.find(r=>r.method==='PATCH'&&r.p.endsWith('/connections/github-1'));assert(saved);assert(!('api_token'in saved.body));assert(!('webhook_secret'in saved.body));checks.push('editing leaves stored credentials untouched when password fields are blank');
 await s.click('[data-mirror-time="github/demo"]');await until(()=>repos.github.mirror_time,'mirror saved');await s.click('[data-move-on-merge="github/demo"]');await until(()=>repos.github.move_on_merge,'merge switch saved');await s.click('[data-publish-on-release="github/demo"]');await until(()=>repos.github.publish_on_release,'release switch saved');await until(async()=>await s.eval('document.querySelector(\'[data-move-on-merge="github/demo"]\').getAttribute("aria-checked")')==='true','the merge switch still reads on after the release switch saves');await button('Backfill');await until(()=>has('3 linked'),'backfill report');assert(await has('Unknown issue keys: MISSING-1'));await button('Test');await until(()=>has('Verified host'),'connection test');checks.push('mirror, move-on-merge and publish-on-release switches save; backfill details and connection tests remain functional');
 await until(()=>has('1h held'),'server formatted duration');await s.click('[aria-label="Radd user for developer"]');await until(()=>has('Mapped person'),'people picker');await s.click('[role="dialog"] button',text=>text==='Mapped person');enabled.delete('auth');await refresh();await until(()=>has('Mapped person (unavailable)'),'missing person directory retains choice');enabled.add('auth');await refresh();await until(async()=>!await has('Mapped person (unavailable)'),'person directory restored');await button('Map and log');await until(()=>has('Replayed: developer (1).'),'identity replay');assert.equal(writes.at(-1).body.user_id,'person-1');await until(()=>has('mapped by hand'),'mapping refreshed');await s.click('[aria-label="Unmap developer"]');await until(()=>mapped.length===0,'mapping removed');checks.push('actual person picker preserves selection across Auth withdrawal; mapping replays held time and unmapping refreshes rows');
 enabled.delete('projects');enabled.delete('timelogging');await refresh();await until(()=>has('Projects are unavailable.'),'project fallback');await until(()=>has('Saved category (categories unavailable)'),'category fallback');assert.equal(repos.github.project_id,'project-1');assert.equal(repos.github.time_category_id,'category-1');enabled.add('projects');enabled.add('timelogging');await refresh();await until(()=>has('TEST · Sample project'),'project restore');await until(()=>has('Development'),'category restore');checks.push('missing dependent lookup owners preserve saved project and work-category IDs');
 deny='/api/v1/github/repos';await invalidate();await until(()=>has('Access denied to connector data'),'denied repo read');assert(!await has('github/demo'));deny=null;await invalidate();await until(()=>has('github/demo'),'repo recovery');checks.push('denied refresh hides stale repository rows and a successful retry recovers');
 hold='/api/v1/github/connections/github-1/test';await button('Test');await until(()=>pending.length>0,'held mutation');const ab=aborted.length;enabled.delete('github');await refresh();await until(()=>has('forgejo/demo'),'fallback provider');hold=null;flush();assert.equal(aborted.length,ab,'a write in flight is never aborted');enabled.add('github');await refresh();await until(()=>has('github/demo'),'requested provider restored');assert(!await has('Verified host'));assert.equal(await s.eval('document.querySelectorAll("[role=tab]").length'),3);checks.push('open provider withdrawal lets an in-flight write finish; saved URL selection restores exactly one tab');
 await nav('/settings/vcs?host=gitlab');await until(()=>has('gitlab/demo'),'URL-selected tab');assert.equal(await s.eval('document.querySelector("[role=tab][aria-selected=true]")?.textContent.trim()'),'GitLab');checks.push('the URL carries the selected connector tab');
 broken.add('gitlab');versions.gitlab=2;await refresh();await until(()=>has('forgejo/demo'),'failed provider fallback');assert(!await has('gitlab/demo'));broken.delete('gitlab');versions.gitlab=3;await refresh();await until(()=>has('gitlab/demo'),'provider bundle recovery');checks.push('failed provider bundle withdraws its tab; replacement activation restores the requested provider');
 hold='/api/v1/gitlab/repos';await invalidate();await until(()=>pending.length>0,'held read');const rb=aborted.length;enabled.delete('vcs');await refresh();await until(()=>exists('[data-plugin-missing="page"]'),'VCS removed');await until(()=>aborted.length>rb,'VCS read aborted');hold=null;flush();enabled.add('vcs');await refresh();await until(()=>has('gitlab/demo'),'VCS restored');checks.push('shared VCS owner withdrawal removes the open page and aborts reads; restoration is fresh');
 broken.add('vcs');versions.vcs=2;await refresh();await until(()=>has('This plugin page could not be loaded'),'VCS bundle failure');broken.delete('vcs');versions.vcs=3;await refresh();await until(()=>has('gitlab/demo'),'VCS bundle recovery');checks.push('failed shared VCS bundle shows the generic page fallback and replacement activation recovers');
 await button('Edit');await until(()=>has('Save host'),'open credential editor');await fill('API token (optional)','temporary-secret');admin=false;await s.eval("window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['radd-sdk','me']})");await until(()=>has('You do not have permission'),'permission withdrawn');assert(!await exists('input[type=password]'));admin=true;await s.eval("window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['radd-sdk','me']})");await until(()=>has('gitlab/demo'),'permission restored');assert(!await exists('input[type=password]'));checks.push('permission loss disposes sensitive drafts and restoration returns to a fresh list');
 await until(()=>s.eval("[...document.querySelectorAll('[data-repo-name]')].every(el=>el.clientWidth>=100&&el.scrollWidth<=el.clientWidth)"),'repository names fit');await s.screenshot('/tmp/radd-vcs-settings-dark.png');await s.eval("document.documentElement.classList.add('light')");await new Promise(resolve=>setTimeout(resolve,500));await s.screenshot('/tmp/radd-vcs-settings-light.png');
 assert(!s.consoleErrors.some(error=>/TypeError|Minified React error|Invalid hook|Uncaught/.test(error)),JSON.stringify(s.consoleErrors));
 console.log(JSON.stringify({passed:true,checks,requests:requests.length,writes:writes.length,aborted:aborted.length}));
}finally{for(const finish of pending)finish();await browser?.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}

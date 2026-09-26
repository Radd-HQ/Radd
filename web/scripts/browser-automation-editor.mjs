/** Full Automations UI from actual bundles; actual backend catalog, isolated mock records. */
import assert from 'node:assert/strict';
import http from 'node:http';
import {readFileSync,existsSync,statSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
import {openBrowser} from './lib/cdp.mjs';
const root=new URL('../../',import.meta.url).pathname,dist=path.join(root,'web/dist');
const fixtures=JSON.parse(execFileSync(path.join(root,'server/.venv/bin/python'),[path.join(root,'web/scripts/automation-ui-fixture.py')],{cwd:path.join(root,'server'),encoding:'utf8'}));
const enabled=new Set(['fixture','projects','auth','items','pages','cycles','fields','labels','workflow','teams','releases','forms','itemtypes','notify','mailintake','github']);
const remotes=new Set(['fixture','automations','projects','auth','items','pages','cycles','fields','labels','workflow','teams','releases','forms','itemtypes']);
const broken=new Set(),versions={},requests=[],aborted=[],pending=[],writes=[],checks=[];
let hold=null,deny=null,admin=true;
const project={id:'project-1',key:'TEST',name:'Sample project',permissions:['project.manage'],description:'',created_at:'2026-09-01T00:00:00Z'};
const seedNodes=[{id:'trigger',type:'trigger.event',kind:'trigger',params:{event:'item.updated'}},{id:'priority',type:'action.set_priority',kind:'action',params:{priority:'high'}}];
let rule={id:'saved',name:'Saved rule',enabled:false,version:2,orientation:'vertical',position:0,last_run_at:null,last_run_status:'',created_at:'2026-09-01T00:00:00Z',updated_at:'2026-09-01T00:00:00Z',nodes:seedNodes,edges:[{source:'trigger',port:'out',target:'priority'}],triggers:[{node_id:'trigger',event_type:'item.updated',schedule:null,next_run_at:null,last_run_at:null}]};
const report=detail=>({rule_id:'saved',item_id:'item-1',matched:true,trigger_node_id:'trigger',nodes:[],dropped:[],findings:[],would_apply:[{type:'action.set_priority',params:{priority:'high'},resolves:true,refused:false,detail,node_id:'priority',item_key:'TEST-1',resolved:{}}]});
const oldVersion={id:'version-1',automation_id:'saved',version:1,name:'Historic rule',created_by_id:'admin',created_by_name:'Admin',created_at:'2026-09-01T00:00:00Z',note:'Original policy',restored_from:null,node_count:2,nodes:seedNodes,edges:rule.edges,orientation:'vertical'};
const run=id=>({id,automation_id:'saved',trigger_node_id:'trigger',source:'manual',event_id:null,event_type:'',started_at:'2026-09-26T00:00:00Z',finished_at:'2026-09-26T00:00:01Z',status:'applied',actor_id:'admin',item_keys:['TEST-1'],actions_applied:1,actions_skipped:0,error:''});
const harness=`import{createElement as h,useState}from'react';import{definePlugin,SlotId,Slot,SettingsPage,useContributedCommands}from'@radd/plugin-sdk';
function Harness(){const[integration,setIntegration]=useState('github');const commands=useContributedCommands({entityType:'item',entityId:'item-1',projectId:'project-1'});window.__automationHarness={setIntegration,commands};return h(SettingsPage,{title:'Integration proof'},h(Slot,{id:SlotId.integrationSettings,integration,label:'Renamed integration'}),h('div',{'data-commands':true},commands.map(command=>h('button',{key:command.id,onClick:()=>command.run().catch(error=>window.__commandError=String(error))},command.label))));}
export default definePlugin({contributions:[{id:'proof',slot:SlotId.settingsPage,match:'/settings/automation-integration-proof',render:()=>h(Harness)}]});`;
function currentCatalog(){return {...fixtures.catalog,nodes:fixtures.catalog.nodes.filter(node=>enabled.has(node.plugin)),triggers:fixtures.catalog.triggers.filter(trigger=>enabled.has(trigger.plugin))};}
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,'http://fixture'),p=url.pathname;
 if(p.startsWith('/plugins/')){const[,,name,...parts]=p.split('/');const file=path.join(root,'server/src/radd/modules',name,'ui/dist',...parts);if(broken.has(name)||name!=='fixture'&&!existsSync(file)){res.statusCode=404;res.end();return;}res.setHeader('content-type',p.endsWith('.css')?'text/css':'text/javascript');res.end(name==='fixture'?harness:readFileSync(file));return;}
 if(p.startsWith('/api/')){
  let raw='';for await(const chunk of req)raw+=chunk;const body=raw?JSON.parse(raw):null;
  const request={p,method:req.method,...Object.fromEntries(url.searchParams),body};requests.push(request);
  if(req.method!=='GET'&&!p.endsWith('/preferences'))writes.push(request);
  res.on('close',()=>{if(!res.writableEnded)aborted.push(request);});res.setHeader('content-type','application/json');
  let data=[],status=200;
  if(p.endsWith('/auth/me'))data={id:'admin',name:'Admin',email:'admin@example.test',instance_role:admin?'admin':'member',global_role:admin?'admin':'member',permissions:[]};
  else if(p.endsWith('/capabilities'))data={capabilities:[],plugins:[...enabled],remotes:[...enabled].filter(name=>remotes.has(name)).map(name=>({name,remote_entry:`/plugins/${name}/remoteEntry.js?v=${versions[name]??1}`,ui_api_version:'1.12.0'})),nav:[{plugin:'fixture',key:'proof',path:'/settings/automation-integration-proof',section:'settings',label:'Integration proof',requires:[]},...(enabled.has('automations')?[{plugin:'automations',key:'automations',path:'/settings/automations',section:'settings',group:'Server',label:'Automations',requires:['automation.manage']}]:[])],widget_types:[],view_types:[]};
  else if(p==='/api/v1/automations/catalog')data=currentCatalog();
  else if(p==='/api/v1/automations/templates')data=fixtures.templates.filter(template=>enabled.has(template.plugin));
  else if(p==='/api/v1/automations/runnable')data=[{id:'saved',name:'Run saved policy'}];
  else if(p==='/api/v1/automations'&&req.method==='GET')data=[rule];
  else if(p==='/api/v1/automations'||p==='/api/v1/automations/saved'&&req.method==='PATCH'){rule={...rule,...body,name:body.name?.trim()??rule.name,version:rule.version+1};data=rule;}
  else if(p.endsWith('/versions/1/restore')){rule={...rule,name:oldVersion.name,nodes:oldVersion.nodes,edges:oldVersion.edges,version:rule.version+1};data=rule;}
  else if(p.endsWith('/versions/1'))data=oldVersion;
  else if(p.endsWith('/versions'))data=[oldVersion];
  else if(p.endsWith('/runs'))data=[run('run-1'),run('run-2')];
  else if(p.endsWith('/runs/run-1'))data={...run('run-1'),report:report('First recorded report')};
  else if(p.endsWith('/runs/run-2'))data={...run('run-2'),report:report('Second recorded report')};
  else if(p.endsWith('/test')||p.endsWith('/preview'))data=report('Draft preview '+body.name);
  else if(p.endsWith('/samples/events'))data={event_type:request.event_type,sampled:1,paths:[{path:'item.key',examples:['TEST-1'],repeated:false}],changed_fields:['priority'],example:{item:{key:'TEST-1'}},subjects:['item'],declared_schema:{},declared_paths:[]};
  else if(p.endsWith('/samples/records'))data=[{id:7,created_at:'2026-09-26T00:00:00Z',payload:{item:{key:'TEST-1'}}}];
  else if(p==='/api/v1/projects'){data=[project];res.setHeader('X-Total-Count','1');}
  else if(p==='/api/v1/projects/project-1'||p==='/api/v1/projects/by-key/TEST')data=project;
  else if(p==='/api/v1/items/link-search')data=[{id:'item-1',key:'TEST-1',title:'Seed issue'}];
  else if(p==='/api/v1/pages/search')data={results:[{page_id:'page-1',title:'Seed page'}]};
  else if(p==='/api/v1/fields')data=[{id:'field-1',key:'severity',name:'Severity',field_type:'text',type:'text',config:{},required:false,position:0,project_ids:[]}];
  else if(p==='/api/v1/labels')data=[{id:'label-1',name:'Urgent'}];
  else if(p.endsWith('/summary'))data={total:1,related_count:0,permissions:[]};
  else if(p.includes('/notifications'))data={items:[],notifications:[],unread_count:0,total:0};
  else if(p.includes('/preferences'))data={};
  if(deny===p){status=403;data={detail:'Access denied for this report'};}
  const finish=()=>{res.statusCode=status;res.end(JSON.stringify(data));};
  if(hold===p)pending.push(finish);else finish();return;
 }
 const f=path.join(dist,p),target=existsSync(f)&&statSync(f).isFile()?f:path.join(dist,'index.html');res.setHeader('content-type',target.endsWith('.js')?'text/javascript':target.endsWith('.css')?'text/css':'text/html');res.end(readFileSync(target));
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let browser;
try{
 browser=await openBrowser({port:18842,profile:await mkdtemp('/tmp/radd-automation-editor-'),scale:1});const s=browser.session;
 const body=()=>s.eval('document.body?.innerText??""');
 const until=async(fn,label)=>{for(let i=0;i<250;i++){if(await fn())return;await new Promise(r=>setTimeout(r,40));}throw Error(label+': '+await body()+' '+JSON.stringify(s.consoleErrors));};
 const has=text=>s.eval(`document.body?.innerText.includes(${JSON.stringify(text)})`),exists=selector=>s.eval(`!!document.querySelector(${JSON.stringify(selector)})`);
 const refresh=()=>s.eval("window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['capabilities']})");
 const invalidate=()=>s.eval("void window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['automations']})");
 const nav=p=>s.navigate(`http://127.0.0.1:${server.address().port}${p}`);
 const button=label=>s.click('button',new Function('text',`return text.trim()===${JSON.stringify(label)}`));
 const fill=async(label,value)=>{const selector=await s.eval(`(()=>{const label=[...document.querySelectorAll('label')].find(el=>el.textContent.trim()===${JSON.stringify(label)});return label?.htmlFor?'#'+CSS.escape(label.htmlFor):null;})()`);assert(selector,label+' input');await s.click(selector);await s.eval(`document.querySelector(${JSON.stringify(selector)}).select()`);await s.send('Input.insertText',{text:value});};
 const stabilize=async selector=>{await s.eval(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'center'})`);await s.eval('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');};
 const select=async(label,text)=>{const selector=await s.eval(`(()=>{const label=[...document.querySelectorAll('label')].find(el=>el.textContent.trim()===${JSON.stringify(label)});return label?.htmlFor?'#'+CSS.escape(label.htmlFor):null;})()`);assert(selector,label+' select');await s.click(selector);await s.click('[role="option"]',new Function('value',`return value.trim()===${JSON.stringify(text)}`));};
 const flush=()=>{while(pending.length)pending.shift()();};
 const edit=async()=>{await s.click('[aria-label="Edit Saved rule"]');await until(()=>has('Automation name'),'editor');};
 await nav('/settings/automation-integration-proof');await until(()=>has('Integration proof'),'harness');assert(!await exists('[data-integration-automations]'));assert(!requests.some(request=>request.p.startsWith('/api/v1/automations')));checks.push('absent Automations contributes neither integration UI nor command discovery');
 enabled.add('automations');await refresh();await until(()=>has('Renamed integration automations'),'integration');await until(()=>has('Run saved policy'),'manual command');
 const githubTemplate=fixtures.templates.find(template=>template.plugin==='github');assert(githubTemplate);await until(()=>has(githubTemplate.name),"integration templates");checks.push('integration templates use registry owner despite an unrelated display label');
 const templatesBefore=writes.length;await button(githubTemplate.name);await until(()=>has('Create automation'),'template draft');assert.equal(writes.length,templatesBefore);assert.equal(await s.eval(`document.querySelector('input[placeholder="Auto-triage blockers"]').value`),githubTemplate.name);assert.equal(await s.eval('document.querySelector("form input[type=checkbox]").checked'),false);await s.click('[role="dialog"] button[aria-label="Close"]');checks.push('integration template opens a disabled unsaved draft and closing it writes nothing');

 await s.eval('window.__retainedCommand=window.__automationHarness.commands[0]');enabled.delete('automations');await refresh();await until(async()=>!await exists('[data-integration-automations]'),'integration withdrawn');const before=writes.length;assert.match(await s.eval('window.__retainedCommand.run().then(()=>"unexpected",error=>String(error))'),/no longer available/);assert.equal(writes.length,before);
 enabled.add('automations');await refresh();await until(()=>has('Run saved policy'),'command restored');assert.equal(await s.eval('document.querySelectorAll("[data-commands] button").length'),1);checks.push('retained manual commands refuse after withdrawal and re-enable without duplicates');
 hold='/api/v1/automations/saved/run';await button('Run saved policy');await until(()=>pending.length>0,'held command');const commandAbort=aborted.length;enabled.delete('automations');await refresh();await until(()=>aborted.length>commandAbort,'command abort');hold=null;flush();enabled.add('automations');await refresh();await until(()=>has('Run saved policy'),'command recovery');checks.push('provider withdrawal cancels a real manual command request');

 await nav('/settings/automations');await until(()=>exists('[aria-label="Edit Saved rule"]'),'owner page');await edit();await until(()=>exists('.react-flow__node[data-id="priority"]'),'graph nodes');
 await until(()=>s.eval('getComputedStyle(document.querySelector(".react-flow__node[data-id=priority]")).visibility==="visible"'),'measured node');await s.click('[data-node-id="priority"]');await until(()=>has('Priority'),'rich priority inspector');await until(()=>exists('[data-tokenizable="Priority"]'),'token toggle');await fill('Automation name','Edited draft');assert(await s.eval(`document.querySelector(${JSON.stringify('input[placeholder="Auto-triage blockers"]')}).getBoundingClientRect().height>=30`));await button('Run');await until(()=>has('Draft preview Edited draft'),'draft preview');assert.equal(writes.at(-1).body.name,'Edited draft');assert(writes.at(-1).body.nodes.some(node=>node.type==='action.set_priority'));checks.push('actual graph, rich action inspector and dry run use current draft content');
 await select('Run it on','A page');await fill('Find a page','Seed');await until(()=>requests.some(request=>request.p==='/api/v1/pages/search'),'page search');await select('As if it ran on','Seed page');enabled.delete('pages');await refresh();await until(()=>has('Page selection is unavailable'),'missing Pages');assert(await has('page-1 (selected page)'));await until(()=>s.eval("window.__RADD_QUERY_CLIENT__.getQueryCache().findAll({queryKey:['automations']}).every(q=>q.state.fetchStatus==='idle')"),'catalog refreshed after Pages withdrawal');await button('Run');await until(()=>writes.at(-1)?.body?.subject_id==='page-1','saved page still submitted '+JSON.stringify(writes.slice(-2)));enabled.add('pages');await refresh();await until(()=>has('Seed page'),'Pages restored');await select('Run it on','An issue');
 enabled.delete('fields');enabled.delete('labels');enabled.delete('projects');await refresh();await until(()=>has('Fields choices are unavailable'),'fields withdrawn');assert(await has('Labels choices are unavailable'));assert(await has('Selection unavailable · project-1'));enabled.add('fields');enabled.add('labels');enabled.add('projects');await refresh();await until(()=>has('TEST · Sample project'),'providers restored');checks.push('Pages, Projects, Fields and Labels withdraw independently; selected project/page IDs survive and restore');
 await s.eval("document.querySelector('input[placeholder=\"Auto-triage blockers\"]').scrollIntoView({block:'start'})");await s.screenshot('/tmp/radd-automation-editor-overview.png');
 await s.screenshot('/tmp/radd-automation-editor-open-dark.png');await s.eval("document.documentElement.classList.add('light')");await s.screenshot('/tmp/radd-automation-editor-open-light.png');await s.eval("document.documentElement.classList.remove('light')");

 await button('Save changes');await until(()=>has('Saved'),'saved receipt');assert.equal(rule.name,'Edited draft');assert.equal(rule.nodes.length,2);checks.push('saving preserves the graph and advances the version');
 await s.click('[role="tab"]',t=>t==='Runs');await until(()=>exists('[data-run-row="run-1"]'),'runs');await s.click('[data-run-row="run-1"]');await until(()=>has('First recorded report'),'first report');hold='/api/v1/automations/saved/runs/run-2';await s.click('[data-run-row="run-2"]');await until(()=>pending.length>0,'second held');assert(!await has('First recorded report'));hold=null;flush();await until(()=>has('Second recorded report'),'second report');deny='/api/v1/automations/saved/runs/run-2';await invalidate();await until(()=>has('Access denied for this report'),'report refusal');assert(!await has('Second recorded report'));deny=null;checks.push('switching reports clears old content and a denied refresh cannot expose cached report data');
 await s.click('[role="tab"]',t=>t==='Versions');await until(()=>exists('[data-version-row="1"]'),'versions');await s.click('[data-version-row="1"] button');await until(()=>exists('[data-version-preview="1"] .react-flow'),'readonly preview');await stabilize('[aria-label="Restore version 1"]');await s.click('[aria-label="Restore version 1"]');await until(()=>exists('[role="dialog"]'),'restore confirmation');await s.click('[role="dialog"] button',t=>t==='Restore');await until(()=>has('Historic rule'),'restored rule');assert.equal(rule.name,'Historic rule');checks.push('version preview renders read-only and confirmed restore adopts the returned graph');
 await s.click('[role="tab"]',t=>t==='Dry run');await until(()=>s.eval("window.__RADD_QUERY_CLIENT__.getQueryCache().findAll().some(q=>q.queryKey.includes('projects.first')&&q.queryKey.at(-1)===false)"),'default project settled');hold='/api/v1/automations/saved/test';await button('Run');await until(()=>pending.length>0,'held dry run');const abortBefore=aborted.length;await fill('Automation name','Temporary name');await until(()=>aborted.length>abortBefore,'input change abort');await fill('Automation name','Historic rule');hold=null;flush();await new Promise(resolve=>setTimeout(resolve,120));assert(!await exists('[data-run-result]'));checks.push('A→B→A input changes abort the first preview and cannot resurrect its result');
 hold='/api/v1/automations/saved';await button('Save changes');await until(()=>pending.length>0,'held save');const saveAbort=aborted.length;enabled.delete('automations');await refresh();await until(()=>exists('[data-plugin-missing="page"]'),'page withdrawal');await until(()=>aborted.length>saveAbort,'save transport aborted');hold=null;flush();enabled.add('automations');await refresh();await until(()=>exists('[aria-label^="Edit "]'),'fresh page');checks.push('withdrawing an open editor cancels save transport and re-enable reads authoritative server state');
 broken.add('automations');versions.automations=2;await refresh();await until(()=>has('This plugin page could not be loaded'),'failed bundle');broken.delete('automations');versions.automations=3;await refresh();await until(()=>exists('[aria-label^="Edit "]'),'bundle recovery');checks.push('failed bundle produces a page fallback and a replacement activation recovers');
 hold='/api/v1/automations';await invalidate();await until(()=>pending.length>0,'held list read');const readAbort=aborted.length;enabled.delete('automations');await refresh();await until(()=>aborted.length>readAbort,'list read aborted');hold=null;flush();enabled.add('automations');await refresh();await until(()=>exists('[aria-label^="Edit "]'),'list after read withdrawal');checks.push('withdrawing the list cancels read observers and re-enable requests fresh data');
 rule={...rule,name:'Saved unavailable trigger',nodes:[{...seedNodes[0],params:{event:'github.push'}},seedNodes[1]]};enabled.delete('github');await invalidate();await refresh();await until(()=>exists('[aria-label="Edit Saved unavailable trigger"]'),'saved unknown rule');await s.click('[aria-label="Edit Saved unavailable trigger"]');await until(()=>s.eval('document.querySelector(".react-flow__node[data-id=trigger]")&&getComputedStyle(document.querySelector(".react-flow__node[data-id=trigger]")).visibility==="visible"'),'unknown trigger measured');await s.click('[data-node-id="trigger"]');await until(()=>has('github.push (unavailable trigger)'),'saved unknown trigger remains visible');checks.push('a saved trigger from an unavailable owner stays visible without changing the saved graph');
 admin=false;await s.eval("window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['radd-sdk','me']})");await until(()=>has('You need the automation.manage permission'),'permission withdrawal');assert(!await exists('input[placeholder="Auto-triage blockers"]'));admin=true;await s.eval("window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['radd-sdk','me']})");await until(()=>exists('[aria-label="Edit Saved unavailable trigger"]'),'permission recovery');assert(!await exists('input[placeholder="Auto-triage blockers"]'));checks.push('loss of management permission closes the editor; restored permission returns to a fresh authorized list');


 await s.screenshot('/tmp/radd-automation-editor-dark.png');await s.eval("document.documentElement.classList.add('light')");await s.screenshot('/tmp/radd-automation-editor-light.png');
 assert(!s.consoleErrors.some(error=>/Invalid hook|Maximum update depth|not exported/.test(error)));console.log(JSON.stringify({passed:true,checks,requests:requests.length,writes:writes.length,aborted:aborted.length}));
}finally{hold=null;while(pending.length)pending.shift()();if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}

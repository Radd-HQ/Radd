/** RADD-1340: live backend changes, inactive tabs, and cached automation metadata. */
import assert from 'node:assert/strict';
import http from 'node:http';
import {readFileSync, existsSync, statSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import path from 'node:path';
import {openBrowser} from './lib/cdp.mjs';
import {CORE_PLUGINS} from './lib/core-plugins.mjs';
const dist = new URL('../dist/', import.meta.url).pathname;
const plugins = ['github','forgejo','gitlab'].map(name => ({id:name,name,version:'1',core:false,state:'enabled',active:true,live_supported:true,runtime_state:"enabled",pending_processes:0,runtime_errors:[],can_toggle:true,capabilities:[],origin:'builtin',dependencies:[],problems:[],description:`${name} connector`}));
let catalogReads=0, templateReads=0;
const connectorReads=[];
const titles={github:'GitHub',forgejo:'Forgejo',gitlab:'GitLab'};
const active=()=>plugins.filter(p=>p.active);
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,'http://fixture'), p=url.pathname;
 if(p.startsWith('/plugins/')){
  const [, ,name,...parts]=p.split('/'),file=new URL(`../../server/src/radd/modules/${name}/ui/dist/${parts.join('/')}`,import.meta.url).pathname;
  if(!existsSync(file)){res.writeHead(404);res.end();return;}
  res.setHeader('content-type','text/javascript');res.end(readFileSync(file));return;
 }
 if(p.startsWith('/api/')){
  let data=[];
  if(p.endsWith('/auth/me'))data={id:'admin',name:'Admin',email:'admin@example.test',global_role:'admin',instance_role:'admin',permissions:['*'],timezone:'UTC'};
  else if(p==='/api/v1/plugins')data=plugins;
  else if(p.match(/\/plugins\/[^/]+\/disable$/)){
   const row=plugins.find(x=>p.includes(`/${x.id}/`));row.state='disabled';row.runtime_state='applying';row.pending_processes=1;data=plugins;
  }
  // Core plugins (vcs, automations) are bundled and always loaded, with the nav their servers declare;
  // the connectors are optional remotes that contribute the Version control tabs, so each active one
  // serves its real bundle.
  else if(p.includes('capabilities'))data={capabilities:[],nav:[{plugin:'vcs',key:'vcs',icon:'git-branch',path:'/settings/vcs',section:'settings',group:'Issues',label:'Version control',requires:[]},{plugin:'automations',key:'automations',icon:'workflow',path:'/settings/automations',section:'settings',group:'Server',label:'Automations',requires:[]}],plugins:[...CORE_PLUGINS,...active().map(x=>x.name)],remotes:active().map(x=>({name:x.name,remote_entry:`/plugins/${x.name}/remoteEntry.js`,ui_api_version:'1.13.0'})),widget_types:[],view_types:[]};
  else if(p==='/api/v1/automations/catalog'){
   catalogReads++;
   data={triggers:[{event_type:'item.updated',label:'Issue updated',group:'Items',item_scoped:true},...active().map(x=>({event_type:`${x.name}.push`,label:`${titles[x.name]} push`,group:titles[x.name],item_scoped:false}))],nodes:[],operators:[],schedule_kinds:[],trigger_kinds:[],tokens:[],payload_paths:[],node_arity:[],manual_trigger:"__manual__",schedule_trigger:"__schedule__",can_act_as:false,max_chain_depth:5};
  }
  else if(p==='/api/v1/automations/templates'){
   templateReads++;data=active().map(x=>({key:`${x.name}.sample`,name:`${titles[x.name]} sample`,group:titles[x.name],description:'Fixture template',nodes:[],edges:[]}));
  }
  else if(p.endsWith('/automations/samples/events'))data={paths:[],declared_paths:[],samples:[],sample_count:0,event_type:'item.updated'};
  else if(p.match(/\/(github|forgejo|gitlab)\//)){connectorReads.push(p);data=[];}
  else if(p.endsWith('/projects/summary')||p.endsWith('/page-spaces/summary'))data={total:0,related_count:0,permissions:[]};
  else if(p.includes('notifications'))data={items:[],notifications:[],unread_count:0,total:0};
  else if(p.includes('preferences'))data={};
  else if(p.endsWith('/instance'))data={work_week_days:['mon'],timelog_hours_per_day:8,timelog_days_per_week:5};
  res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify(data));return;
 }
 const file=path.join(dist,p), target=existsSync(file)&&statSync(file).isFile()?file:path.join(dist,'index.html');
 res.setHeader('content-type',target.endsWith('.js')?'text/javascript':target.endsWith('.css')?'text/css':'text/html');res.end(readFileSync(target));
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
let browser;
try{
 browser=await openBrowser({port:18826,profile:await mkdtemp('/tmp/radd-plugin-availability-'),scale:1});
 const s=browser.session,base=`http://127.0.0.1:${server.address().port}`;
 const until=async(predicate,label)=>{for(let i=0;i<450;i++){if(await predicate())return;await new Promise(r=>setTimeout(r,50));}throw Error(label+': '+await s.eval('document.body.innerText')+' '+JSON.stringify(s.consoleErrors));};
 const text=t=>s.eval(`document.body.innerText.toLowerCase().includes(${JSON.stringify(t.toLowerCase())})`);
 const go=async href=>{await s.eval(`document.querySelector('a[href="${href}"]').click()`);};
 const templates=()=>s.eval(`Array.from(document.querySelectorAll('[role=dialog] [data-template]')).map(b=>b.getAttribute('data-template')).sort().join(',')`);
 const closeDialog=()=>s.eval(`document.querySelector('[role="dialog"] [aria-label="Close"]').click()`);
 await s.navigate(base+'/settings/automations');
 await until(()=>text('New rule'),'automations ready');
 // Templates are the loaded connectors' own (RADD-1316): all three are offered before the disable.
 await s.click('button',t=>t.trim()==='From template…');
 await until(async()=>await templates()==='forgejo.sample,github.sample,gitlab.sample','every connector offers its template');
 await closeDialog();await until(()=>s.eval(`!document.querySelector('[role=dialog]')`),'template picker closed');
 await s.click('button',t=>t.trim()==='New rule');
 await until(()=>text('Triggers · GitHub'),'GitHub initially offered');
 assert(await text('Triggers · Forgejo'));
 const initialCatalogReads=catalogReads;
 await s.click('button',t=>t.includes('Back to automations'));
 await go('/settings/plugins');
 await until(()=>text('github connector'),'plugins ready');
 for(const name of ['github','forgejo']){
  await s.eval(`Array.from(document.querySelectorAll('li')).find(li=>li.innerText.includes('${name} connector')).querySelector('button:last-child').click()`);
 }
 await until(()=>text('Applying…'),'pending status');
 assert(await text('Applying plugin changes…'));
 assert(await text('Cancel disable'));
 assert(await text('Disabling across running servers and workers'));
 await s.screenshot('/tmp/radd-plugin-availability-pending.png');
 await go('/settings/vcs');
 await until(()=>s.eval('document.querySelectorAll("[role=tab]").length===3'),'pending providers stay honest');
 const initialTemplateReads=templateReads;
 for(const p of plugins.filter(x=>x.name!=='gitlab')){p.active=false;p.runtime_state='disabled';p.pending_processes=0;}
 await until(()=>s.eval('document.querySelectorAll("[role=tab]").length===1 && document.querySelector("[role=tab]").innerText.includes("GitLab")'),'inactive provider tabs removed');
 // The page carries no ?host=, so the one remaining connector is the selected tab (RADD-1366: the
 // tabs are the connectors' own contributions, not a host list rewritten into the URL).
 assert(await s.eval('document.querySelector("[role=tab][aria-selected=true]")?.innerText.includes("GitLab")'));
 await go('/settings/automations');
 await until(()=>text('New rule'),'return to automations');
 await s.click('button',t=>t.trim()==='New rule');
 await until(()=>catalogReads>initialCatalogReads && text('Triggers · GitLab'),'catalog refreshed in same SPA session');
 assert(!await text('Triggers · GitHub'));assert(!await text('Triggers · Forgejo'));
 await s.screenshot('/tmp/radd-plugin-availability-palette.png');
 // The same SPA session reads the templates afresh: the cached answer named two withdrawn connectors.
 await s.click('button',t=>t.includes('Back to automations'));await until(()=>text('New rule'),'automations list again');
 await s.click('button',t=>t.trim()==='From template…');
 await until(async()=>templateReads>initialTemplateReads&&await templates()==='gitlab.sample','templates refreshed without reload');
 await closeDialog();
 await s.navigate(base+'/settings/vcs?host=github');
 // A deep link to a withdrawn connector waits for the remotes, then says it fell back instead of
 // silently showing another host's settings.
 await until(()=>s.eval('document.querySelectorAll("[role=tab]").length===1 && document.querySelector("[role=tab][aria-selected=true]")?.innerText.includes("GitLab")'),'disabled deep link falls back');
 assert(await text('The requested connector is unavailable. Showing GitLab.'));
 plugins[2].active=false;plugins[2].state='disabled';
 await until(()=>text('No version control connectors are available.'),'all inactive empty state');
 assert(await s.eval('document.querySelectorAll("[role=tab]").length===0'));
 await s.screenshot('/tmp/radd-plugin-availability-empty.png');
 console.log(JSON.stringify({passed:true,checks:['pending disable is explicit','loaded connector tabs remain until acknowledgement','withdrawn connector tabs removed; the remaining one is selected','a deep link to a withdrawn connector says it fell back','catalog and templates refresh without reload','disabled connectors offer no triggers or templates','no connectors leaves the available-connectors empty state'],catalogReads,templateReads}));
}finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}

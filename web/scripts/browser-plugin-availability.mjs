/** RADD-1340: live backend changes, inactive tabs, and cached automation metadata. */
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {openBrowser,until} from './lib/cdp.mjs';
import {CORE_PLUGINS} from './lib/core-plugins.mjs';
import {serveBuiltSpa} from './lib/spa-server.mjs';
import {vcsConnectors} from './lib/vcs-connectors.mjs';
const plugins = ['github','forgejo','gitlab'].map(name => ({id:name,name,version:'1',core:false,state:'enabled',active:true,runtime_state:"enabled",pending_processes:0,runtime_errors:[],can_toggle:true,capabilities:[],origin:'builtin',dependencies:[],problems:[],description:`${name} connector`}));
let catalogReads=0, templateReads=0;
const connectorReads=[];
const titles={github:'GitHub',forgejo:'Forgejo',gitlab:'GitLab'};
const active=()=>plugins.filter(p=>p.active);
const spa=await serveBuiltSpa((req,res,url)=>{
 const p=url.pathname;
 if(p.startsWith('/api/')){
  let data=[];
  if(p.endsWith('/auth/me'))data={id:'admin',name:'Admin',email:'admin@example.test',global_role:'admin',instance_role:'admin',permissions:['*'],timezone:'UTC'};
  else if(p==='/api/v1/plugins')data=plugins;
  else if(p.match(/\/plugins\/[^/]+\/disable$/)){
   const row=plugins.find(x=>p.includes(`/${x.id}/`));row.state='disabled';row.runtime_state='applying';row.pending_processes=1;data=plugins;
  }
  // Core plugins (vcs, automations) are bundled and always loaded, with the nav their servers declare;
  // the connectors ship no UI: vcs draws a Version control tab for each one the server lists (RADD-1435).
  else if(p==='/api/v1/vcs/connectors')data=vcsConnectors(active().map(x=>x.name));
  else if(p.includes('capabilities'))data={capabilities:[],nav:[{plugin:'vcs',key:'vcs',icon:'git-branch',path:'/settings/vcs',section:'settings',group:'Issues',label:'Version control',requires:[]},{plugin:'automations',key:'automations',icon:'workflow',path:'/settings/automations',section:'settings',group:'Server',label:'Automations',requires:[]}],plugins:[...CORE_PLUGINS,...active().map(x=>x.name)],remotes:[],widget_types:[],view_types:[]};
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
  res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify(data));return true;
 }
});
let browser;
try{
 browser=await openBrowser({port:18826,profile:await mkdtemp('/tmp/radd-plugin-availability-'),scale:1});
 const s=browser.session,base=spa.origin;
 const text=t=>s.eval(`document.body.innerText.toLowerCase().includes(${JSON.stringify(t.toLowerCase())})`);
 const go=async href=>{await s.eval(`document.querySelector('a[href="${href}"]').click()`);};
 const templates=()=>s.eval(`Array.from(document.querySelectorAll('[role=dialog] [data-template]')).map(b=>b.getAttribute('data-template')).sort().join(',')`);
 const closeDialog=()=>s.eval(`document.querySelector('[role="dialog"] [aria-label="Close"]').click()`);
 await s.navigate(base+'/settings/automations');
 await until(s,()=>text('New rule'),'automations ready');
 // Templates are the loaded connectors' own (RADD-1316): all three are offered before the disable.
 await s.click('button',t=>t.trim()==='From template…');
 await until(s,async()=>await templates()==='forgejo.sample,github.sample,gitlab.sample','every connector offers its template');
 await closeDialog();await until(s,()=>s.eval(`!document.querySelector('[role=dialog]')`),'template picker closed');
 await s.click('button',t=>t.trim()==='New rule');
 await until(s,()=>text('Triggers · GitHub'),'GitHub initially offered');
 assert(await text('Triggers · Forgejo'));
 const initialCatalogReads=catalogReads;
 await s.click('button',t=>t.includes('Back to automations'));
 await go('/settings/plugins');
 await until(s,()=>text('github connector'),'plugins ready');
 for(const name of ['github','forgejo']){
  await s.eval(`Array.from(document.querySelectorAll('li')).find(li=>li.innerText.includes('${name} connector')).querySelector('button:last-child').click()`);
 }
 await until(s,()=>text('Applying…'),'pending status');
 assert(await text('Applying plugin changes…'));
 assert(await text('Cancel disable'));
 assert(await text('Disabling across running servers and workers'));
 await s.screenshot('/tmp/radd-plugin-availability-pending.png');
 await go('/settings/vcs');
 await until(s,()=>s.eval('document.querySelectorAll("[role=tab]").length===3'),'pending providers stay honest');
 const initialTemplateReads=templateReads;
 for(const p of plugins.filter(x=>x.name!=='gitlab')){p.active=false;p.runtime_state='disabled';p.pending_processes=0;}
 await until(s,()=>s.eval('document.querySelectorAll("[role=tab]").length===1 && document.querySelector("[role=tab]").innerText.includes("GitLab")'),'inactive provider tabs removed');
 // The page carries no ?host=, so the one remaining connector is the selected tab (the tabs are the
 // loaded connectors, not a host list rewritten into the URL).
 assert(await s.eval('document.querySelector("[role=tab][aria-selected=true]")?.innerText.includes("GitLab")'));
 await go('/settings/automations');
 await until(s,()=>text('New rule'),'return to automations');
 await s.click('button',t=>t.trim()==='New rule');
 await until(s,()=>catalogReads>initialCatalogReads && text('Triggers · GitLab'),'catalog refreshed in same SPA session');
 assert(!await text('Triggers · GitHub'));assert(!await text('Triggers · Forgejo'));
 await s.screenshot('/tmp/radd-plugin-availability-palette.png');
 // The same SPA session reads the templates afresh: the cached answer named two withdrawn connectors.
 await s.click('button',t=>t.includes('Back to automations'));await until(s,()=>text('New rule'),'automations list again');
 await s.click('button',t=>t.trim()==='From template…');
 await until(s,async()=>templateReads>initialTemplateReads&&await templates()==='gitlab.sample','templates refreshed without reload');
 await closeDialog();
 await s.navigate(base+'/settings/vcs?host=github');
 // A deep link to a withdrawn connector waits for the connector list, then says it fell back instead of
 // silently showing another host's settings.
 await until(s,()=>s.eval('document.querySelectorAll("[role=tab]").length===1 && document.querySelector("[role=tab][aria-selected=true]")?.innerText.includes("GitLab")'),'disabled deep link falls back');
 assert(await text('The requested connector is unavailable. Showing GitLab.'));
 plugins[2].active=false;plugins[2].state='disabled';
 await until(s,()=>text('No version control connectors are available.'),'all inactive empty state');
 assert(await s.eval('document.querySelectorAll("[role=tab]").length===0'));
 await s.screenshot('/tmp/radd-plugin-availability-empty.png');
 console.log(JSON.stringify({passed:true,checks:['pending disable is explicit','loaded connector tabs remain until acknowledgement','withdrawn connector tabs removed; the remaining one is selected','a deep link to a withdrawn connector says it fell back','catalog and templates refresh without reload','disabled connectors offer no triggers or templates','no connectors leaves the available-connectors empty state'],catalogReads,templateReads}));
}finally{if(browser)await browser.close();await spa.close();}

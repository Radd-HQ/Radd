/** RADD-1340: pending backend changes, inactive tabs, and cached automation metadata. */
import assert from 'node:assert/strict';
import http from 'node:http';
import {readFileSync, existsSync, statSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import path from 'node:path';
import {openBrowser} from './lib/cdp.mjs';
const dist = new URL('../dist/', import.meta.url).pathname;
const plugins = ['github','forgejo','gitlab'].map(name => ({id:name,name,version:'1',core:false,state:'enabled',active:true,restart_required:false,live_supported:false,can_toggle:true,capabilities:[],origin:'builtin',dependencies:[],problems:[],description:`${name} connector`}));
let catalogReads=0, templateReads=0;
const connectorReads=[];
const titles={github:'GitHub',forgejo:'Forgejo',gitlab:'GitLab'};
const active=()=>plugins.filter(p=>p.active);
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,'http://fixture'), p=url.pathname;
 if(p.startsWith('/api/')){
  let data=[];
  if(p.endsWith('/auth/me'))data={id:'admin',name:'Admin',email:'admin@example.test',global_role:'admin',instance_role:'admin',permissions:['*'],timezone:'UTC'};
  else if(p==='/api/v1/plugins')data=plugins;
  else if(p.match(/\/plugins\/[^/]+\/disable$/)){
   const row=plugins.find(x=>p.includes(`/${x.id}/`));row.state='disabled';row.restart_required=row.active;data=plugins;
  }
  else if(p.includes('capabilities'))data={capabilities:[],nav:[],plugins:active().map(x=>x.name),remotes:[],widget_types:[],view_types:[]};
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
 await s.navigate(base+'/settings/automations');
 await until(()=>text('New rule'),'automations ready');
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
 await until(()=>text('Disable pending'),'pending status');
 assert(await text('Plugin changes are waiting for a restart.'));
 assert(await text('Cancel disable'));
 assert(await text('Still active: its integrations and automation nodes remain available'));
 await s.screenshot('/tmp/radd-plugin-availability-pending.png');
 await go('/settings/vcs');
 await until(()=>s.eval('document.querySelectorAll("[role=tab]").length===3'),'pending providers stay honest');
 const initialTemplateReads=templateReads;
 for(const p of plugins.filter(x=>x.name!=='gitlab')){p.active=false;p.restart_required=false;}
 await until(()=>s.eval('document.querySelectorAll("[role=tab]").length===1 && document.querySelector("[role=tab]").innerText.includes("GitLab")'),'inactive provider tabs removed');
 assert(await s.eval('location.search.includes("host=gitlab")'));
 await until(()=>templateReads>initialTemplateReads,'template cache refreshed');
 await go('/settings/automations');
 await until(()=>text('New rule'),'return to automations');
 await s.click('button',t=>t.trim()==='New rule');
 await until(()=>catalogReads>initialCatalogReads && text('Triggers · GitLab'),'catalog refreshed in same SPA session');
 assert(!await text('Triggers · GitHub'));assert(!await text('Triggers · Forgejo'));
 await s.screenshot('/tmp/radd-plugin-availability-palette.png');
 await s.navigate(base+'/settings/vcs?host=github');
 await until(()=>s.eval('location.search.includes("host=gitlab") && document.querySelectorAll("[role=tab]").length===1'),'disabled deep link falls back');
 plugins[2].active=false;plugins[2].state='disabled';
 await until(()=>text('No version control connectors are enabled.'),'all inactive empty state');
 assert(await s.eval('document.querySelectorAll("[role=tab]").length===0'));
 await s.screenshot('/tmp/radd-plugin-availability-empty.png');
 console.log(JSON.stringify({passed:true,checks:['pending disable is explicit','loaded tabs remain until restart','inactive tabs removed','old provider URL falls back','catalog and templates refresh without reload','disabled nodes absent','all inactive empty state'],catalogReads,templateReads}));
}finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}

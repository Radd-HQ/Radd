/** Real Projects/Cycles remotes; verifies picker contracts and lifecycle through the host. */
import assert from 'node:assert/strict';
import { mkdtemp } from 'node:fs/promises';
import { openBrowser, until } from './lib/cdp.mjs';
import { serveBuiltSpa } from './lib/spa-server.mjs';
const enabled=new Set(['fixture']),broken=new Set(),versions={projects:1,cycles:1},requests=[];
let hold=null,release,aborted=0,refuse=null,suffix='';
const project=i=>({id:`p-${i}`,key:`PR${i}`,name:`Project ${String(i).padStart(3,'0')}${suffix}`,description:'full project row',permissions:['item.create'],created_at:'2026-01-01T00:00:00Z'});
const cycle=i=>({id:`c-${i}`,name:`Cycle ${String(i).padStart(3,'0')}${suffix}`,goal:'full cycle row',status:['draft','upcoming','active','completed'][(i-1)%4],start_date:i%4===1?null:'2026-09-01',end_date:i%4===1?null:'2026-09-30',team_ids:['t-1'],project_id:'p-1',created_at:'2026-01-01T00:00:00Z',updated_at:'2026-01-01T00:00:00Z'});
const harness=`import{createElement as h,useState}from'react';import{definePlugin,SlotId,Slot,SettingsPage}from'@radd/plugin-sdk';
function Harness(){const[mode,setMode]=useState('projects.select');const[value,setValue]=useState('p-1');const[row,setRow]=useState(null);const[props,setProps]=useState({});const[closed,setClosed]=useState(false);window.__pickers={setMode,setValue,value,row,setProps,closed,setClosed};return h(SettingsPage,{title:'Picker ownership proof'},h('div',{'data-picker-proof':mode},closed?null:h(Slot,{id:mode,value,label:'Choice',title:'Choose from fixture',...props,onChange:(v,r)=>{setValue(v);setRow(r)},onSelect:r=>{setRow(r);setValue(r?.id??'');setClosed(true)},onClose:()=>setClosed(true),fallback:h('p',{},'Picker unavailable: '+value),errorFallback:h('p',{},'Picker unavailable: '+value)})));}
export default definePlugin({contributions:[{id:'picker-proof',slot:SlotId.settingsPage,match:'/settings/picker-proof',render:()=>h(Harness)}]});`;
const spa=await serveBuiltSpa(async(req,res,url)=>{
 const p=url.pathname;
 if(p.startsWith('/plugins/')){
  const name=p.split('/')[2];if(broken.has(name)){res.writeHead(404);res.end();return true;}
  if(name!=='fixture')return false;
  res.setHeader('content-type','text/javascript');res.end(harness);return true;
 }
 if(p.startsWith('/api/')){
  let data=[];
  const family=p.includes('/projects')?'projects':p.includes('/cycles')?'cycles':null;
  const saved=family&&((family==='projects'&&(/\/projects\/p-/.test(p)||p.includes('/projects/by-key/')))||(family==='cycles'&&p.includes('/cycles/c-')));
  const paged=family&&url.searchParams.get('limit')==='50';
  if(saved||paged){
   const type=saved?'saved':'page';requests.push({family,type,path:p,...Object.fromEntries(url.searchParams)});
   let rows=Array.from({length:125},(_,i)=>family==='projects'?project(i+1):cycle(i+1));
   if(saved){const token=p.split('/').pop();data=rows.find(r=>r.id===token||r.key===token);}
   else{
    const q=url.searchParams.get('q')??'';rows=rows.filter(r=>(r.name+' '+(r.key??'')).includes(q));
    if(family==='cycles'&&url.searchParams.get('include_completed')==='false')rows=rows.filter(r=>r.status!=='completed');
    if(family==='cycles'&&url.searchParams.get('dated_only')==='true')rows=rows.filter(r=>r.start_date);
    const offset=Number(url.searchParams.get('offset')??0);data=rows.slice(offset,offset+50);res.setHeader('X-Total-Count',String(rows.length));
   }
   if(hold===`${family}:${type}`){res.on('close',()=>{if(!res.writableEnded)aborted++;});await new Promise(resolve=>{release=resolve;});}
   if(refuse===family){res.writeHead(403,{'content-type':'application/json'});res.end(JSON.stringify({detail:`${family} denied`}));return true;}
   if(data===undefined){res.writeHead(404,{'content-type':'application/json'});res.end(JSON.stringify({detail:'Not found'}));return true;}
  }else if(p.endsWith('/auth/me'))data={id:'admin',name:'Admin',email:'admin@example.test',instance_role:'admin',global_role:'admin',permissions:['*']};
  else if(p.includes('capabilities'))data={capabilities:[],plugins:[...enabled],remotes:[...enabled].map(name=>({name,remote_entry:`/plugins/${name}/remoteEntry.js?v=${versions[name]??1}`,ui_api_version: '2.0.0'})),nav:[{key:'fixture',plugin:'fixture',path:'/settings/picker-proof',section:'settings',label:'Picker proof',requires:[]}],widget_types:[],view_types:[]};
  else if(p.endsWith('/projects/summary'))data={total:125,related_count:0,permissions:[]};
  else if(p.endsWith('/page-spaces/summary'))data={total:0,related_count:0,permissions:[]};
  else if(p.includes('notifications'))data={items:[],notifications:[],unread_count:0,total:0};
  else if(p.includes('preferences'))data={};
  res.setHeader('content-type','application/json');res.end(JSON.stringify(data));return true;
 }
});
let browser;const checks=[];
try{
 browser=await openBrowser({port:18835,profile:await mkdtemp('/tmp/radd-pickers-'),scale:1});const s=browser.session;
 const ev=code=>s.eval(`(()=>{${code}})()`),text=t=>s.eval(`Array.from(document.querySelectorAll('[data-picker-proof], [role=dialog]')).some(e=>e.innerText.includes(${JSON.stringify(t)}))`);
 const refresh=()=>s.eval("window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['capabilities']})");
 const choose=t=>s.click('button',new Function('v',`return v.includes(${JSON.stringify(t)})`));
 const close=()=>s.click('[role="dialog"] button[aria-label="Close"]');
 const input=async(value)=>ev(`const el=document.querySelector('[role=dialog] input');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,${JSON.stringify(value)});el.dispatchEvent(new Event('input',{bubbles:true}));`);
 const mode=async(name,value,props={})=>{await ev(`window.__pickers.setMode(${JSON.stringify(name)});window.__pickers.setValue(${JSON.stringify(value)});window.__pickers.setProps(${JSON.stringify(props)});window.__pickers.setClosed(false);`);await until(s,()=>s.eval(`document.querySelector('[data-picker-proof]').getAttribute('data-picker-proof')===${JSON.stringify(name)}`),'mode '+name);};
 await s.navigate(`${spa.origin}/settings/picker-proof`);await until(s,()=>text('Picker unavailable: p-1'),'initially absent Projects');assert.equal(requests.filter(r=>r.type==='saved').length,0);assert.equal(await s.eval("window.__RADD_QUERY_CLIENT__.getQueryCache().getAll().filter(q=>q.queryKey[0]==='projects'&&q.queryKey[1]==='page'&&q.queryKey.length===4).length"),0);
 enabled.add('projects');await refresh();await until(s,()=>text('PR1 · Project 001'),'saved project');assert.equal(await s.eval("window.__RADD_QUERY_CLIENT__.getQueryCache().getAll().filter(q=>q.queryKey[0]==='projects'&&q.queryKey[1]==='page'&&q.queryKey.length===4).length"),0);checks.push('absent Projects makes no picker reads; enabled selector resolves its saved ID without browsing');
 await ev("window.__pickers.setProps({permission:'item.create',emptyLabel:'Every project',emptyValue:'__all__'})");await s.click('[data-picker-proof] button');await until(s,()=>text('Project 050'),'project first page');
 assert(requests.some(r=>r.family==='projects'&&r.permission==='item.create'&&r.limit==='50'));
 assert.equal(await s.eval("document.querySelectorAll('[role=dialog] li').length"),50);
 await s.click('button[aria-label="Next project choices"]');await until(s,()=>text('Project 100'),'project second page');await input('125');await until(s,()=>text('Project 125'),'last project search');
 await choose('Project 125');assert.equal(await s.eval('window.__pickers.value'),'p-125');assert.equal(await s.eval('window.__pickers.row.description'),'full project row');
 await s.click('[data-picker-proof] button');await until(s,()=>text('Every project'),'empty sentinel');await choose('Every project');assert.equal(await s.eval('window.__pickers.value'),'__all__');assert.equal(await s.eval('window.__pickers.row'),null);
 checks.push('project paging/search preserve full rows, permission filter and custom empty sentinel');
 await mode('projects.select','pr2',{valueBy:'key'});await until(s,()=>text('PR2 · Project 002'),'project key resolution');assert(requests.some(r=>r.path.endsWith('/by-key/PR2')));
 await s.click('[data-picker-proof] button');await until(s,()=>text('Project 003'),'key choice');await choose('Project 003');assert.equal(await s.eval('window.__pickers.value'),'PR3');checks.push('project key mode normalizes lookup while returning a key and full selected project');

 await ev("window.__RADD_QUERY_CLIENT__.removeQueries({queryKey:['projects','page']})");hold='projects:page';await s.click('[data-picker-proof] button');await until(s,()=>Boolean(release),'held projects');const ab1=aborted;enabled.delete('projects');await refresh();await until(s,()=>text('Picker unavailable: PR3'),'Projects withdrawn');await until(s,()=>aborted>ab1,'project read canceled');assert.equal(await s.eval("document.querySelectorAll('[role=dialog]').length"),0);hold=null;release();release=undefined;suffix=' fresh';
 enabled.add('projects');await refresh();await until(s,()=>text('Project 003 fresh'),'Projects restored');assert.equal(await s.eval('window.__pickers.value'),'PR3');assert.equal(await s.eval("document.querySelectorAll('[data-picker-proof] label').length"),1);checks.push('open Projects withdrawal aborts paging; re-enable resolves fresh labels with one control and preserved key');
 refuse='projects';await ev("window.__pickers.setValue('PR4')");await until(s,()=>text('projects denied'),'denied project');refuse=null;await choose('Retry project name');await until(s,()=>text('Project 004 fresh'),'project retry');
 await ev("window.__pickers.setValue('MISSING')");await until(s,()=>text('Unavailable project'),'missing project');assert.equal(await s.eval('window.__pickers.value'),'MISSING');checks.push('denied project resolution retries; missing project remains saved and unavailable');

 await mode('cycles.select','c-3',{projectId:'p-1',includeCompleted:false,datedOnly:true,emptyLabel:'Backlog',emptyValue:'__backlog__'});await until(s,()=>text('Picker unavailable: c-3'),'initially absent Cycles');assert(!requests.some(r=>r.family==='cycles'&&r.type==='saved'));assert.equal(await s.eval("window.__RADD_QUERY_CLIENT__.getQueryCache().getAll().filter(q=>q.queryKey[0]==='cycles'&&q.queryKey[1]==='page'&&q.queryKey.length===4).length"),0);
 enabled.add('cycles');await refresh();await until(s,()=>text('Cycle 003 fresh'),'saved cycle');assert.equal(await s.eval("window.__RADD_QUERY_CLIENT__.getQueryCache().getAll().filter(q=>q.queryKey[0]==='cycles'&&q.queryKey[1]==='page'&&q.queryKey.length===4).length"),0);
 await s.click('[data-picker-proof] button');await until(s,()=>text('Cycle 099 fresh'),'cycle first filtered page');
 assert(requests.some(r=>r.family==='cycles'&&r.project_id==='p-1'&&r.include_completed==='false'&&r.dated_only==='true'));
 assert.equal(await s.eval("document.querySelector('[data-cycle-scope]').getAttribute('aria-checked')"),'false');
 await s.click('[data-cycle-scope]');await until(s,()=>requests.some(r=>r.family==='cycles'&&r.type==='page'&&!r.project_id),'all cycle query');
 await ev("window.__pickers.setProps({projectId:'p-2',includeCompleted:false,datedOnly:true,emptyLabel:'Backlog',emptyValue:'__backlog__'})");
 await until(s,()=>requests.some(r=>r.family==='cycles'&&r.project_id==='p-2'),'changed project scope');assert.equal(await s.eval("document.querySelector('[data-cycle-scope]').getAttribute('aria-checked')"),'false');
 await until(s,()=>text('Cycle 006 fresh'),'filtered results');await choose('Cycle 006 fresh');assert.equal(await s.eval('window.__pickers.value'),'c-6');assert.equal(await s.eval('window.__pickers.row.goal'),'full cycle row');
 await s.click('[data-picker-proof] button');await until(s,()=>text('Backlog'),'cycle sentinel');await choose('Backlog');assert.equal(await s.eval('window.__pickers.value'),'__backlog__');assert.equal(await s.eval('window.__pickers.row'),null);
 checks.push('Cycles owns ID resolution, full-row callback, project/all scope, changed-scope reset, date/completed filters and empty sentinel');

 const beforeNames=requests.length;await mode('cycles.select','Saved cycle name',{valueBy:'name'});await until(s,()=>text('Saved cycle name'),'named cycle');assert.equal(requests.length,beforeNames);
 await s.click('[data-picker-proof] button');await until(s,()=>text('Cycle 050 fresh'),'cycle names browse');await choose('Cycle 007 fresh');assert.equal(await s.eval('window.__pickers.value'),'Cycle 007 fresh');checks.push('name mode preserves arbitrary saved names without ID lookup and returns the chosen name');
 await mode('cycles.select','c-2',{selectedLabel:'Preloaded cycle'});await until(s,()=>text('Preloaded cycle'),'preloaded label');const beforeLabel=requests.length;await new Promise(r=>setTimeout(r,100));assert.equal(requests.length,beforeLabel);
 await ev("window.__pickers.setProps({disabled:true,selectedLabel:'Preloaded cycle',error:'Fix this',hint:'Hint'})");await until(s,()=>s.eval("document.querySelector('[data-picker-proof] button').disabled"),'disabled cycle');assert.equal(await s.eval("document.querySelector('[data-picker-proof] button').getAttribute('aria-invalid')"),'true');checks.push('provided labels avoid lookup; disabled and error accessibility props are preserved');

 await mode('cycles.select','c-2',{});await until(s,()=>text('Cycle 002 fresh'),'cycle ready');await ev("window.__RADD_QUERY_CLIENT__.removeQueries({queryKey:['cycles','page']})");hold='cycles:page';await s.click('[data-picker-proof] button');await until(s,()=>Boolean(release),'held cycles');const ab2=aborted;enabled.delete('cycles');await refresh();await until(s,()=>text('Picker unavailable: c-2'),'Cycles withdrawn');await until(s,()=>aborted>ab2,'cycle page canceled');hold=null;release();release=undefined;
 enabled.add('cycles');await refresh();await until(s,()=>text('Cycle 002 fresh'),'Cycles restored');checks.push('open Cycles withdrawal cancels paging and preserves selected ID across re-enable');
 hold='cycles:saved';await ev("window.__pickers.setValue('c-8')");await until(s,()=>Boolean(release),'held saved cycle');const ab3=aborted;enabled.delete('cycles');await refresh();await until(s,()=>aborted>ab3,'saved cycle canceled');hold=null;release();release=undefined;enabled.add('cycles');await refresh();await until(s,()=>text('Cycle 008 fresh'),'saved cycle recovered');checks.push('saved cycle resolution is canceled and stale replies cannot replace re-enabled results');
 refuse='cycles';await s.click('[data-picker-proof] button');await until(s,()=>text('Retry cycles'),'denied cycle directory');refuse=null;await choose('Retry cycles');await until(s,()=>text('Cycle 050 fresh'),'cycle retry');await close();checks.push('denied cycle browsing provides explicit retry without showing stale rows');

 await mode('projects.picker','',{});await until(s,()=>s.eval("[...document.querySelectorAll('[role=dialog] button')].some(b=>b.textContent.includes('Project 050'))"),'standalone ProjectPicker');await s.click('[role=dialog] button',v=>v.includes('Project 009'));assert.equal(await s.eval('window.__pickers.row.key'),'PR9');assert(await s.eval('window.__pickers.closed'));
 await mode('cycles.choices','',{emptyLabel:null,projectId:'p-3'});await until(s,()=>text('Cycle 050 fresh'),'standalone CycleChoices');assert(requests.some(r=>r.family==='cycles'&&r.project_id==='p-3'));
 await until(s,()=>s.eval("getComputedStyle(document.querySelector('[role=dialog]')).opacity==='1'"),'modal animation settled');await s.screenshot('/tmp/radd-cycle-contribution.png');await choose('Cycle 010 fresh');assert.equal(await s.eval('window.__pickers.row.id'),'c-10');checks.push('standalone picker contributions preserve complete callbacks and caller dismissal');
 assert(!s.consoleErrors.some(e=>/Invalid hook|not exported|Maximum update depth/.test(e)));
 console.log(JSON.stringify({passed:true,checks,requests:requests.length,aborted}));
}finally{release?.();if(browser)await browser.close();await spa.close();}

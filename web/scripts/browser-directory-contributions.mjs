/** Auth and Teams (core plugins bundled with the host, RADD-1373) own directory queries; the SDK
 * supplies generic control behavior. The server's loaded set is the only lifecycle they have. */
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {openBrowser,until} from './lib/cdp.mjs';
import {CORE_PLUGINS} from './lib/core-plugins.mjs';
import {serveBuiltSpa} from './lib/spa-server.mjs';
// Every other core plugin stays loaded (the Audit page below is one); Auth and Teams come and go.
const enabled=new Set(['fixture']),requests=[];
const alwaysLoaded=CORE_PLUGINS.filter(name=>!['auth','teams'].includes(name));
let hold=false,release,aborted=0,refuse=false;
const harness=`import {createElement as h,useState} from 'react';import{definePlugin,SlotId,SettingsPage,DirectorySelect}from'@radd/plugin-sdk';
function Harness(){const [values,setValues]=useState({});return h(SettingsPage,{title:'Directory contribution proof'},...[
 ['person','auth.people',undefined],['team','teams.teams',undefined],['member','teams.candidates',{teamId:'example',purpose:'member'}],['manager','teams.candidates',{teamId:'example',purpose:'manager'}],['owner','teams.candidates',{teamId:'example',purpose:'owner'}]
].map(([id,source,context])=>h('div',{key:id,'data-picker':id,style:{marginBottom:12}},h(DirectorySelect,{source,context,label:'Choose '+id,emptyLabel:'Choose…',value:values[id]??null,onChange:v=>setValues(x=>({...x,[id]:v}))}))));}
export default definePlugin({contributions:[{id:'directory-proof',slot:SlotId.settingsPage,match:'/settings/directory-proof',render:()=>h(Harness)}]});`;
const spa=await serveBuiltSpa(async(req,res,url)=>{
 const p=url.pathname;
 if(p.startsWith('/plugins/')){
  if(p.split('/')[2]!=='fixture'){res.writeHead(404);res.end();return true;}
  res.setHeader('content-type','text/javascript');res.end(harness);return true;
 }
 if(p.startsWith('/api/')){
  let data=[];
  if(p.endsWith('/auth/me'))data={id:'admin',name:'Admin',email:'admin@example.test',instance_role:'admin',global_role:'admin',permissions:['*']};
  else if(p.includes('capabilities'))data={capabilities:[],plugins:[...alwaysLoaded,...enabled],remotes:[{name:'fixture',remote_entry:'/plugins/fixture/remoteEntry.js',ui_api_version:'1.4.0'}],nav:[{key:'fixture',plugin:'fixture',path:'/settings/directory-proof',section:'settings',label:'Directory proof',requires:[]}],widget_types:[],view_types:[]};
  else if(p.endsWith('/users/directory')||p.endsWith('/teams')||p.includes('-candidates')){
   // Ignore unrelated host directory reads, which lack pagination parameters.
   if(url.searchParams.has('limit')){
    requests.push({path:p,q:url.searchParams.get('q'),offset:Number(url.searchParams.get('offset')),purpose:url.searchParams.get('purpose')});
    if(hold){res.on('close',()=>{if(!res.writableEnded)aborted++;});await new Promise(resolve=>{release=resolve;});}
    if(refuse){res.writeHead(403,{'content-type':'application/json'});res.end(JSON.stringify({detail:'Directory access refused'}));return true;}
    const q=url.searchParams.get('q')??'',offset=Number(url.searchParams.get('offset')??0),limit=Number(url.searchParams.get('limit')??50);
    const prefix=p.includes('steward-candidates')?url.searchParams.get('purpose'):p.includes('member-candidates')?'member':p.endsWith('/teams')?'team':'person';
    const all=Array.from({length:125},(_,i)=>({id:`${prefix}-${i+1}`,name:`${prefix} ${String(i+1).padStart(3,'0')}`})).filter(row=>row.name.includes(q));
    data=all.slice(offset,offset+limit);res.setHeader('X-Total-Count',String(all.length));
   }
  }
  else if(p.endsWith('/projects/summary')||p.endsWith('/page-spaces/summary'))data={total:0,related_count:0,permissions:[]};
  else if(p.includes('notifications'))data={items:[],notifications:[],unread_count:0,total:0};
  else if(p.includes('preferences'))data={};
  res.setHeader('content-type','application/json');res.end(JSON.stringify(data));return true;
 }
});
let browser;const checks=[];
try{
 browser=await openBrowser({port:18831,profile:await mkdtemp('/tmp/radd-directory-'),scale:1});const s=browser.session;
 const text=t=>s.eval(`document.body.innerText.includes(${JSON.stringify(t)})`);
 const refresh=()=>s.eval(`window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['capabilities']})`);
 const change=async(fn)=>{fn();await refresh();};
 // Directory reads are shared and cached by key (RADD-1373): drop them before a step that must see a request.
 const forget=key=>s.eval(`window.__RADD_QUERY_CLIENT__.removeQueries({queryKey:${JSON.stringify(key)}})`);
 const open=id=>s.eval(`document.querySelector('[data-picker="${id}"] button').focus();document.querySelector('[data-picker="${id}"] button').click()`);
 const close=()=>s.eval(`document.querySelector('[role="dialog"] [aria-label="Close"]').click()`);
 const filter=async value=>s.eval(`(()=>{const el=document.querySelector('[role="dialog"] input[type="search"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,${JSON.stringify(value)});el.dispatchEvent(new Event('input',{bubbles:true}));})()`);
 await s.navigate(`${spa.origin}/settings/directory-proof`);await until(s,()=>text('Directory contribution proof'),'harness mounted');
 assert.equal(await s.eval(`document.querySelectorAll('[data-picker] button:disabled').length`),5);assert.equal(requests.length,0);checks.push('unavailable providers show disabled controls without requests');
 await change(()=>{enabled.add('auth');enabled.add('teams');});await until(s,()=>s.eval(`document.querySelectorAll('[data-picker] button:disabled').length===0`),'providers activated');
 await open('person');await until(s,()=>text('person 050'),'person first page');assert.equal(await s.eval(`document.querySelectorAll('[role="dialog"] li').length`),50);assert(await text('of 125'));
 assert(await s.eval(`document.querySelector('[role="dialog"]').contains(document.activeElement)`),'modal owns focus');
 await s.eval(`document.querySelector('[aria-label="Next people"]').click()`);await until(s,()=>text('person 051'),'second page');assert.equal(requests.at(-1).offset,50);
 await filter('125');await until(s,()=>text('person 125'),'search matches last result');assert.equal(requests.at(-1).offset,0);assert.equal(await s.eval(`document.querySelectorAll('[role="dialog"] li').length`),1);
 await s.screenshot('/tmp/radd-directory-picker.png');await s.click('[role="dialog"] button',t=>t.trim()==='person 125');await until(s,()=>s.eval(`document.querySelector('[data-picker="person"]').textContent.includes('person 125')`),'selection persisted');
 assert(await s.eval(`!document.querySelector('[role="dialog"]')`));checks.push('people pagination/search preserves totals and selected label; modal owns focus');
 await open('team');await until(s,()=>text('team 001'),'team directory');assert(requests.at(-1).path.endsWith('/teams'));await close();
 for(const purpose of ['member','manager','owner']){await open(purpose);await until(s,()=>text(purpose+' 001'),purpose+' choices');assert.equal(requests.at(-1).purpose,purpose==='member'?null:purpose);assert(requests.at(-1).path.endsWith(purpose==='member'?'/member-candidates':'/steward-candidates'));await close();}checks.push('Teams owns directory and member/manager/owner candidate semantics');
 await forget(['users','choices']);hold=true;await open('person');await until(s,()=>Boolean(release),'request held');const personAborts=aborted;await change(()=>enabled.delete('auth'));await until(s,()=>aborted>personAborts,'withdrawal aborts');assert(!await s.eval(`document.querySelector('[role="dialog"]')!==null`));assert(await s.eval(`document.querySelector('[data-picker="person"] button').disabled`));assert(await s.eval(`document.querySelector('[data-picker="person"]').textContent.includes('person 125')`));assert(!await s.eval(`document.querySelector('[data-picker="team"] button').disabled`));release();release=undefined;hold=false;checks.push('Auth withdrawal closes the dialog and aborts its read, retains the selected value, and leaves Teams usable');
 await change(()=>enabled.add('auth'));await until(s,()=>s.eval(`!document.querySelector('[data-picker="person"] button').disabled`),'auth restored');const beforeReopen=requests.length;await open('person');await until(s,async()=>requests.length>beforeReopen&&await text('person 001'),'reopen reads afresh after the aborted read');assert.equal(await s.eval(`document.querySelectorAll('[role="dialog"]').length`),1);assert.equal(await s.eval(`document.querySelectorAll('[data-picker="person"] button[aria-haspopup="dialog"]').length`),1);await close();checks.push('re-enable restores one control; the aborted read left nothing cached and reopening fetches');
 await open('person');await until(s,()=>text('person 001'),'cached rows shown');refuse=true;await s.eval(`window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['users','choices']})`);await until(s,()=>text('Directory access refused'),'permission error');assert.equal(await s.eval(`document.querySelectorAll('[role="dialog"] li').length`),0);refuse=false;await s.click('[role="dialog"] button',t=>t.trim()==='Retry choices');await until(s,()=>text('person 001'),'retry works');checks.push('a refused refresh hides the cached rows and offers retry');
 await s.eval(`document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))`);await until(s,()=>s.eval(`!document.querySelector('[role="dialog"]')`),'Escape dismisses');assert(await s.eval(`document.activeElement.getAttribute('aria-label')==='Choose person'`));checks.push('shared modal dismisses and restores focus');
 await forget(['teamMembers']);hold=true;await open('owner');await until(s,()=>Boolean(release),'candidate request held');const priorAborts=aborted;
 await change(()=>enabled.delete('teams'));await until(s,()=>aborted>priorAborts,'Teams withdrawal aborts');assert(!await s.eval(`document.querySelector('[role="dialog"]')!==null`));assert(!await s.eval(`document.querySelector('[data-picker="person"] button').disabled`));release();release=undefined;hold=false;
 await change(()=>enabled.add('teams'));await until(s,()=>s.eval(`!document.querySelector('[data-picker="owner"] button').disabled`),'Teams restored');await open('owner');await until(s,()=>text('owner 001'),'owner choices restored');await close();checks.push('Teams withdrawal aborts candidates, leaves Auth usable, and recovers');
 await s.navigate(`${spa.origin}/settings/audit`);await until(s,()=>s.eval(`document.querySelector('[aria-label="Filter by person"]')!==null`),'host audit adapter mounted');
 await s.eval(`document.querySelector('[aria-label="Filter by person"]').click()`);await until(s,()=>text('person 001'),'host adapter opens contributed directory');await s.click('[role="dialog"] button',t=>t.trim()==='person 001');await until(s,()=>s.eval(`location.search.includes('actor=person-1')`),'host receives selected value');checks.push('existing host Audit page delegates to Auth and receives selection');
 assert(!s.consoleErrors.some(error=>error.includes('Invalid hook')||error.includes('not exported')));
 console.log(JSON.stringify({passed:true,checks}));
}finally{release?.();if(browser)await browser.close();await spa.close();}

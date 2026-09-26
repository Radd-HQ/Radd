/** Exercise each owner's actual option contribution (every owner is a bundled core plugin since RADD-1392), the SDK
 *  controls, and an optional owner's failed remote — a fixture remote, since no optional plugin contributes a directory. */
import assert from 'node:assert/strict';
import http from 'node:http';
import { existsSync, readFileSync, statSync } from 'node:fs';
import { mkdtemp } from 'node:fs/promises';
import path from 'node:path';
import { openBrowser } from './lib/cdp.mjs';
import { CORE_PLUGINS } from './lib/core-plugins.mjs';
const dist = new URL('../dist/', import.meta.url).pathname;
const owners = {users:'auth','users/directory':'auth',roles:'auth','roles/assignable':'auth',teams:'teams','teams/directory':'teams',states:'workflow','issue-types':'itemtypes',releases:'releases',forms:'forms','page-spaces':'pages',groups:'groups'};
// The optional owner: a remote contributing a directory through the same SDK contract a real one would.
const optionalOwners = {'fixture-things':'optional-owner'};
const enabled = new Set(['fixture']), broken = new Set(), versions = {}, requests = [];
let hold = false, release, aborted = 0, refuse = false, suffix = '';
const harness = `import{createElement as h,useState}from'react';import{definePlugin,SlotId,SettingsPage,OptionChoices,OptionSelect,OptionTextField,OptionNameValues}from'@radd/plugin-sdk';
function Harness(){const[resource,setResource]=useState('users');const[kind,setKind]=useState('select');const[value,setValue]=useState('saved');const[names,setNames]=useState(['legacy']);const[scope,setScope]=useState({});const[canBrowse,setCanBrowse]=useState(true);const[open,setOpen]=useState(true);const[presets,setPresets]=useState([]);window.__options={setResource,setKind,setValue,value,names,setNames,setScope,setCanBrowse,setOpen,setPresets};const props={resource,label:'Target',value,onChange:setValue,scope,canBrowse,presets};return h(SettingsPage,{title:'Option contribution proof'},h('div',{'data-option-proof':true},kind==='choices'?(open?h(OptionChoices,{resource,scope,canBrowse,presets,selectedValues:names,onSelect:r=>setValue(r.value),onClose:()=>setOpen(false),footer:h('span',{},'Caller footer')}):null):kind==='text'?h(OptionTextField,{...props,suggestions:['{{item.key}}']}):kind==='names'?h(OptionNameValues,{resource,scope,canBrowse,label:'Names',value:names,onChange:setNames}):h(OptionSelect,props)));}
export default definePlugin({contributions:[{id:'options-proof',slot:SlotId.settingsPage,match:'/settings/options-proof',render:()=>h(Harness)}]});`;
const optionalOwner = `import{api,definePlugin,optionContribution}from'@radd/plugin-sdk';
export default definePlugin({contributions:[optionContribution({resource:'fixture-things',noun:'fixture things',meta:{entities:['project','role']},
  fetch:({q,limit,offset,scope,signal})=>api.getPaged('/fixture-things/options',{signal,query:{...scope,q,limit:String(limit),offset:String(offset)}}),
  resolve:({value,scope,signal})=>api.get('/fixture-things/options',{signal,query:{...scope,value,limit:'1'}})})]});`;
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://fixture'), p = url.pathname;
  if (p.startsWith('/plugins/')) {
    const [, , name, ...parts] = p.split('/');
    if (broken.has(name)) {res.writeHead(404);res.end();return;}
    res.setHeader('content-type','text/javascript');
    res.end(name === 'fixture' ? harness : name === 'optional-owner' ? optionalOwner : readFileSync(new URL(`../../server/src/radd/modules/${name}/ui/dist/${parts.join('/')}`,import.meta.url)));
    return;
  }
  if (p.startsWith('/api/')) {
    let data = [];
    const resource = p.slice('/api/v1/'.length).replace(/\/options$/,'');
    if (p.endsWith('/options') && (Object.hasOwn(owners, resource) || Object.hasOwn(optionalOwners, resource))) {
      const query = Object.fromEntries(url.searchParams);
      requests.push({resource,...query});
      // Captured before a delayed response, so a stale reply cannot silently become fresh.
      const currentSuffix = suffix;
      if ((hold === 'browse' && !query.value) || (hold === 'resolve' && query.value === 'saved')) {res.on('close',()=>{if(!res.writableEnded)aborted++;});await new Promise(resolve=>{release=resolve;});}
      if (refuse) {res.writeHead(403,{'content-type':'application/json'});res.end(JSON.stringify({detail:'Directory denied'}));return;}
      const all = Array.from({length:125},(_,i)=>({value:i===0?'saved':`${resource}-${i+1}`,label:`${resource} choice ${String(i+1).padStart(3,'0')}${currentSuffix}`,hint:`hint ${i+1}`}));
      const matched = query.value ? all.filter(r=>r.value===query.value) : all.filter(r=>r.label.includes(query.q??''));
      data = matched.slice(Number(query.offset??0),Number(query.offset??0)+Number(query.limit??50));
      res.setHeader('X-Total-Count',String(matched.length));
    } else if(p.endsWith('/auth/me')) data={id:'admin',name:'Admin',email:'admin@example.test',instance_role:'admin',global_role:'admin',permissions:['*']};
    else if(p.includes('capabilities')) data={capabilities:[],plugins:[...enabled],remotes:[...enabled].filter(name=>!CORE_PLUGINS.includes(name)).map(name=>({name,remote_entry:`/plugins/${name}/remoteEntry.js?v=${versions[name]??1}`,ui_api_version:'1.6.0'})),nav:[{key:'fixture',plugin:'fixture',path:'/settings/options-proof',section:'settings',label:'Options proof',requires:[]}],widget_types:[],view_types:[]};
    else if(p.endsWith('/projects/summary')||p.endsWith('/page-spaces/summary')) data={total:0,related_count:0,permissions:[]};
    else if(p.includes('notifications')) data={items:[],notifications:[],unread_count:0,total:0};
    else if(p.includes('preferences')) data={};
    res.setHeader('content-type','application/json');res.end(JSON.stringify(data));return;
  }
  const file=path.join(dist,p),target=existsSync(file)&&statSync(file).isFile()?file:path.join(dist,'index.html');
  res.setHeader('content-type',target.endsWith('.js')?'text/javascript':target.endsWith('.css')?'text/css':'text/html');res.end(readFileSync(target));
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
let browser;const checks=[];
try {
  browser=await openBrowser({port:18834,profile:await mkdtemp('/tmp/radd-options-'),scale:1});const s=browser.session;
  const ev=code=>s.eval(`(()=>{${code}})()`);
  const text=t=>s.eval(`document.body.innerText.includes(${JSON.stringify(t)})`);
  const until=async(fn,label)=>{for(let i=0;i<250;i++){if(await fn())return;await new Promise(r=>setTimeout(r,40));}throw Error(label+': '+await s.eval('document.body.innerText')+' '+JSON.stringify(s.consoleErrors));};
  const refresh=()=>s.eval("window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['capabilities']})");
  const input=async(selector,value)=>ev(`const el=document.querySelector(${JSON.stringify(selector)});Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,${JSON.stringify(value)});el.dispatchEvent(new Event('input',{bubbles:true}));`);
  const choose=async(name)=>{await s.click('button',new Function('t',`return t.includes(${JSON.stringify(name)})`));};
  await s.navigate(`http://127.0.0.1:${server.address().port}/settings/options-proof`);
  await until(()=>text('saved (unavailable)'),'saved unavailable value');assert.equal(requests.length,0);
  assert(await s.eval("document.querySelector('[data-option-proof] button').disabled"));
  await ev("window.__options.setKind('text')");await until(()=>s.eval("document.querySelector('[data-option-proof] input')!==null"),'text fallback');
  await input('[data-option-proof] input','{{item.key}}');assert.equal(await s.eval('window.__options.value'),'{{item.key}}');
  assert.equal(requests.length,0);checks.push('initially absent sources make no reads; saved references and free text survive');

  for(const owner of new Set(Object.values(owners)))enabled.add(owner);
  await refresh();await ev("window.__options.setKind('select');window.__options.setValue('saved')");
  for(const resource of Object.keys(owners)) {
    await ev(`window.__options.setResource(${JSON.stringify(resource)})`);
    await until(()=>text(resource+' choice 001'),'resolve '+resource);
    await s.click('[data-option-proof] button');
    await until(()=>text(resource+' choice 050'),'browse '+resource);
    assert(requests.some(r=>r.resource===resource&&r.value==='saved'&&r.limit==='1'));
    assert(requests.some(r=>r.resource===resource&&r.offset==='0'&&r.limit==='50'));
    const tags=await s.eval(`window.__RADD_QUERY_CLIENT__.getQueryCache().getAll().filter(q=>q.queryKey[0]==='directory-options'&&q.queryKey[1]===${JSON.stringify(resource)}).map(q=>q.meta?.entities)`);
    assert(tags.length&&tags.every(t=>t?.includes('project')&&t?.includes('role')),resource+' invalidation metadata');
    await choose(resource+' choice 002');await until(()=>s.eval(`window.__options.value===${JSON.stringify(resource+'-2')}`),'chosen '+resource);
    enabled.delete(owners[resource]);await refresh();
    await until(()=>text(resource+'-2 (unavailable)'),'withdraw '+resource);
    assert.equal(await s.eval('window.__options.value'),resource+'-2');
    assert.equal(await s.eval("document.querySelectorAll('[role=dialog]').length"),0);
    enabled.add(owners[resource]);await refresh();await until(()=>text(resource+' choice 002'),'restore '+resource);
    assert.equal(await s.eval("document.querySelectorAll('[data-option-proof] label').length"),1);
    await ev("window.__options.setValue('saved')");
  }
  checks.push('all twelve sources from eight actual owners (all bundled) resolve, browse, withdraw and restore with saved values, owner endpoints and cache metadata');

  await ev("window.__options.setResource('users')");await until(()=>text('users choice 001'),'people ready');await s.click('[data-option-proof] button');
  await until(()=>text('users choice 050'),'first page');await s.click('button[aria-label="Next people"]');
  await until(()=>text('users choice 100'),'second page');assert(requests.some(r=>r.resource==='users'&&r.offset==='50'));
  await input('[role="dialog"] input[type="search"]','125');await until(()=>text('users choice 125'),'filtered last row');
  assert.equal(await s.eval("document.querySelectorAll('[role=dialog] ul li').length"),1);
  await choose('users choice 125');checks.push('bounded paging and debounced search reach the full directory');

  await ev("window.__options.setResource('roles/assignable');window.__options.setScope({project_id:'project-a'});window.__options.setValue('saved')");
  await until(()=>text('roles/assignable choice 001'),'scoped resolve');await s.click('[data-option-proof] button');await until(()=>text('roles/assignable choice 050'),'scoped rows');
  assert(requests.some(r=>r.resource==='roles/assignable'&&r.project_id==='project-a'&&r.value==='saved'));
  assert(requests.some(r=>r.resource==='roles/assignable'&&r.project_id==='project-a'&&r.offset==='0'));
  await ev("window.__options.setScope({space_id:'space-b'})");await until(()=>requests.some(r=>r.resource==='roles/assignable'&&r.space_id==='space-b'&&r.offset==='0'),'changed scope read');
  await choose('roles/assignable choice 002');checks.push('role scope reaches both resolution and browsing and changes invalidate open results');

  await ev("window.__options.setCanBrowse(false);window.__options.setPresets([{value:'__clear__',label:'Clear assignment',hint:''}])");
  await new Promise(r=>setTimeout(r,100));const before=requests.length;
  await s.click('[data-option-proof] button');await choose('Clear assignment');assert.equal(await s.eval('window.__options.value'),'__clear__');assert.equal(requests.length,before);
  checks.push('caller presets work without directory permission and make no provider requests');

  await ev("window.__options.setCanBrowse(true);window.__options.setPresets([]);window.__options.setScope({});window.__options.setResource('groups');window.__options.setValue('')");
  await until(()=>text('Choose…'),'new empty group control');
  await ev("window.__RADD_QUERY_CLIENT__.removeQueries({queryKey:['directory-options','groups',{q:'',page:0}]})");hold='browse';await s.click('[data-option-proof] button');await until(()=>Boolean(release),'held browse');
  const ab1=aborted;enabled.delete('groups');await refresh();await until(()=>s.eval("document.querySelector('[role=dialog]')===null"),'withdrawn open picker');
  await until(()=>aborted>ab1,'withdrawal abort');hold=false;release();release=undefined;suffix=' fresh';
  enabled.add('groups');await refresh();await until(()=>s.eval("!document.querySelector('[data-option-proof] button').disabled"),'source re-enabled');
  await s.click('[data-option-proof] button');await until(()=>text('groups choice 001 fresh'),'fresh rows');
  assert.equal(await s.eval("document.querySelectorAll('[role=dialog]').length"),1);await choose('groups choice 002 fresh');
  checks.push('withdrawing an open source (server drops Groups) cancels its request; re-enable starts fresh without duplicate modals or the late reply');

  await ev("window.__RADD_QUERY_CLIENT__.removeQueries({queryKey:['directory-options','groups','value','saved']})");hold='resolve';await ev("window.__options.setValue('saved')");await until(()=>Boolean(release),'held saved-value resolution');
  const ab2=aborted;enabled.delete('groups');await refresh();await until(()=>text('saved (unavailable)'),'resolution withdrawn');await until(()=>aborted>ab2,'resolution abort');
  hold=false;release();release=undefined;suffix=' fresh!';enabled.add('groups');await refresh();await until(()=>text('groups choice 001 fresh!'),'resolution recovered from a new read, not the held reply');
  checks.push('saved-value resolution is canceled on withdrawal and cannot display a late result');

  // Every core owner is bundled and cannot fail to load (RADD-1373; Pages since RADD-1392). An optional owner's
  // remote can, and no optional plugin contributes a directory, so a fixture remote plays that owner.
  enabled.add('optional-owner');await refresh();
  await ev("window.__options.setResource('fixture-things')");await until(()=>text('fixture-things choice 001'),'optional owner ready');
  broken.add('optional-owner');versions['optional-owner']=2;await refresh();await until(()=>s.consoleErrors.some(e=>e.includes('"optional-owner" failed to load')),'failed remote quarantined');
  await until(()=>text('saved (unavailable)'),'failed remote');assert.equal(await s.eval('window.__options.value'),'saved');
  broken.delete('optional-owner');versions['optional-owner']=3;await refresh();await until(()=>text('fixture-things choice 001'),'remote recovered');
  assert.equal(await s.eval("document.querySelectorAll('[data-option-proof] label').length"),1);
  checks.push('a failed optional owner bundle (a fixture remote contributing a directory) preserves the value and recovers through a new activation');
  await ev("window.__options.setResource('groups')");await until(()=>text('groups choice 001 fresh'),'groups again');

  refuse=true;await ev("window.__options.setValue('groups-3')");await until(()=>text('Directory denied'),'denied resolution');assert(!await text('groups choice 001 fresh'));
  refuse=false;await choose('Retry choice');await until(()=>text('groups choice 003 fresh'),'resolve retry');
  await ev("window.__RADD_QUERY_CLIENT__.removeQueries({queryKey:['directory-options','groups',{q:'',page:0}]})");refuse=true;await s.click('[data-option-proof] button');await until(()=>text('Retry choices'),'denied browse');refuse=false;await choose('Retry choices');await until(()=>text('groups choice 050 fresh'),'browse retry');
  await choose('groups choice 004 fresh');checks.push('denied reads report errors, hide previous rows and recover through explicit retry');

  await ev("window.__options.setKind('names');window.__options.setNames(['legacy','saved'])");await until(()=>text('Browse directory groups'),'multi control mounted');await choose('Browse directory groups');await until(()=>text('groups choice 050 fresh'),'multi choices');
  assert(await s.eval("Array.from(document.querySelectorAll('[role=dialog] button')).find(e=>e.textContent.includes('groups choice 001')).disabled"));
  await choose('groups choice 005 fresh');assert.deepEqual(await s.eval('window.__options.names'),['legacy','saved','groups-5']);
  enabled.delete('groups');await refresh();await until(()=>s.eval("Array.from(document.querySelectorAll('[data-option-proof] button')).some(e=>e.textContent.includes('Browse choices')&&e.disabled)"),'multi fallback');
  assert.deepEqual(await s.eval('window.__options.names'),['legacy','saved','groups-5']);checks.push('multi-value editing preserves old names and prevents duplicate picks across source withdrawal');

  await ev("window.__options.setKind('choices');window.__options.setOpen(true)");await until(()=>text('Caller footer'),'standalone unavailable modal');assert(await text('Saved values are preserved'));
  await until(()=>s.eval("getComputedStyle(document.querySelector('[role=dialog]')).opacity==='1'&&getComputedStyle(document.querySelector('[role=dialog]').parentElement).opacity==='1'"),'fallback animation settled');
  await s.screenshot('/tmp/radd-option-unavailable.png');await s.click('button[aria-label="Close"]');
  await until(()=>s.eval("document.querySelector('[role=dialog]')===null"),'fallback close');checks.push('standalone unavailable picker retains caller footer and can be dismissed');
  enabled.add('groups');await refresh();await ev("window.__options.setOpen(true)");await until(()=>text('groups choice 050 fresh'),'standalone restored');await until(()=>s.eval("getComputedStyle(document.querySelector('[role=dialog]')).opacity==='1'&&getComputedStyle(document.querySelector('[role=dialog]').parentElement).opacity==='1'"),'directory animation settled');await s.screenshot('/tmp/radd-option-directory.png');
  assert(!s.consoleErrors.some(e=>/Invalid hook|not exported|Maximum update depth/.test(e)));
  console.log(JSON.stringify({passed:true,checks,requests:requests.length,aborted}));
} finally {release?.();if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}

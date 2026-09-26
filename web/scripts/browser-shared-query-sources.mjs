/**
 * RADD-1373: consumers of one contributed query source share ONE query, and TanStack keeps one
 * queryFn per query — whichever consumer rendered last. A disabled consumer (A) must therefore not
 * be able to fail an enabled one (B): an entity invalidation, or A's own refetch, used to throw
 * "unavailable or disabled" from A's queryFn and leave B failed with zero provider requests.
 */
import assert from 'node:assert/strict';
import http from 'node:http';
import { readFileSync, existsSync, statSync } from 'node:fs';
import { mkdtemp } from 'node:fs/promises';
import path from 'node:path';
import { openBrowser } from './lib/cdp.mjs';
import { CORE_PLUGINS } from './lib/core-plugins.mjs';
const dist=new URL('../dist/',import.meta.url).pathname,enabled=new Set(['fixture','probe']),broken=new Set(),versions={},requests=[],summaryReads=[];
let hold=null,release,aborted=0,refuse=null,suffix='';
const field=()=>({id:'cost',key:'cost',name:'Cost'+suffix,type:'number',options:null,required:false,default_value:null,display:null,project_ids:[],indexed:false,ai_visible:false,source:'local',restricted:false,created_at:'2026-01-01'});
const spec={key:'action.set_custom_field',plugin:'automations',kind:'action',label:'Set custom field',description:'',group:'Items',params_schema:{},keywords:'',default_params:{},reads_event:false,produces_findings:false,dynamic_ports:false,dynamic_outputs:false,shape_params:[],terminal:false,ports:['ok'],default_ports:['ok'],outputs:[],needs_items:true,permission:''};
const catalog={nodes:[spec],node_arity:[],triggers:[],trigger_kinds:[],tokens:[],schedule_kinds:[],operators:[],can_act_as:false,max_chain_depth:8};
const rule={id:'saved',name:'Catalog lifecycle',enabled:false,version:1,orientation:'vertical',triggers:[],position:0,last_run_at:null,last_run_status:'',created_at:'2026-09-25T12:00:00Z',updated_at:'2026-09-25T12:00:00Z',nodes:[{id:'a',kind:'action',type:'action.set_custom_field',params:{key:'cost',value:7},x:0,y:0}],edges:[]};
const harness=`import{createElement as h}from'react';import{definePlugin,SlotId,SettingsPage,useContributedQuery}from'@radd/plugin-sdk';
function A(){const q=useContributedQuery('probe.echo',{value:'x'},{enabled:false});window.__A=q;return h('p',{'data-a':1},q.isError?'A failed: '+q.error.message:'A ok');}
function B(){const q=useContributedQuery('probe.echo',{value:'x'});window.__B=q;return h('p',{'data-b':1},q.isError?'B failed: '+q.error.message:q.data?.value??'pending');}
function Harness(){return h(SettingsPage,{title:'Shared'},h(B),h(A));}
export default definePlugin({contributions:[{id:'query-proof',slot:SlotId.settingsPage,match:'/settings/query-proof',render:()=>h(Harness)}]});`;
const probe=`import{definePlugin,api}from'@radd/plugin-sdk';export default definePlugin({querySources:[{key:'probe.echo',meta:{entities:['probe']},fetch:(args,signal)=>api.get('/probe',{signal,query:{value:args.value}})}]});`;
const collision=`import{definePlugin}from'@radd/plugin-sdk';export default definePlugin({querySources:[{key:'fields.catalog',fetch:async()=>[{name:'stolen'}]}]});`;
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,'http://fixture'),p=url.pathname;
 if(p.startsWith('/plugins/')){const[,,name,...parts]=p.split('/');if(broken.has(name)){res.writeHead(404);res.end();return;}res.setHeader('content-type',p.endsWith('.css')?'text/css':'text/javascript');res.end(name==='fixture'?harness:name==='probe'?probe:name==='collision'?collision:readFileSync(new URL(`../../server/src/radd/modules/${name}/ui/dist/${parts.join('/')}`,import.meta.url)));return;}
 if(p.startsWith('/api/')){let data=[];
  if(['/api/v1/fields','/api/v1/labels','/api/v1/probe'].includes(p)){
   const kind=p.split('/').pop(),value=url.searchParams.get('value');requests.push({kind,value});
   data=kind==='fields'?[field()]:kind==='labels'?[{id:'l1',name:'Urgent'+suffix,color:null,created_at:'2026-01-01'}]:{value};
   if(hold===(kind==='probe'?kind+':'+value:kind)){res.on('close',()=>{if(!res.writableEnded)aborted++;});await new Promise(resolve=>{release=resolve;});}
   if(refuse===kind){res.writeHead(403,{'content-type':'application/json'});res.end(JSON.stringify({detail:kind+' denied'}));return;}
  }else if(p.endsWith('/fields/settings-summary')){summaryReads.push(p);data={};}
  else if(p.endsWith('/auth/me'))data={id:'admin',name:'Admin',email:'admin@example.test',instance_role:'admin',global_role:'admin',permissions:['*']};
  else if(p.includes('capabilities'))data={capabilities:[],plugins:[...enabled],remotes:[...enabled].filter(name=>!CORE_PLUGINS.includes(name)).map(name=>({name,remote_entry:`/plugins/${name}/remoteEntry.js?v=${versions[name]??1}`,ui_api_version:'1.9.0'})),nav:[{key:'automations',plugin:'automations',path:'/settings/automations',section:'settings',label:'Automations',requires:[]},{key:'fixture',plugin:'fixture',path:'/settings/query-proof',section:'settings',label:'Query proof',requires:[]}],widget_types:[],view_types:[]};
  else if(p.endsWith('/automations/catalog'))data=catalog;else if(p.endsWith('/automations'))data=[rule];
  else if(p.endsWith('/summary'))data={total:0,related_count:0,permissions:[]};else if(p.includes('notifications'))data={items:[],notifications:[],unread_count:0,total:0};else if(p.includes('preferences'))data={};
  res.setHeader('content-type','application/json');res.end(JSON.stringify(data));return;
 }
 const f=path.join(dist,p),target=existsSync(f)&&statSync(f).isFile()?f:path.join(dist,'index.html');res.setHeader('content-type',target.endsWith('.js')?'text/javascript':target.endsWith('.css')?'text/css':'text/html');res.end(readFileSync(target));
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));let browser;const checks=[];
try{
 browser=await openBrowser({port:18847,profile:await mkdtemp('/tmp/radd-query-sources-'),scale:1});const s=browser.session;
 const ev=code=>s.eval(`(()=>{${code}})()`),text=t=>s.eval(`document.body.innerText.includes(${JSON.stringify(t)})`);
 const until=async(fn,label)=>{for(let i=0;i<250;i++){if(await fn())return;await new Promise(r=>setTimeout(r,40));}throw Error(label+': '+await s.eval('document.body.innerText')+' '+JSON.stringify(s.consoleErrors));};
 const source=(name,value)=>s.eval(`document.querySelector('[data-source="${name}"] p')?.textContent===${JSON.stringify(value)}`);
 const echo=(which,value)=>s.eval(`document.querySelector('[data-echo="${which}"]')?.textContent===${JSON.stringify(value)}`);
 const refresh=()=>s.eval("window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['capabilities']})");
 const retry=name=>ev(`void window.__catalog.${name}.refetch()`);
 const probeQuery=value=>`window.__RADD_QUERY_CLIENT__.getQueryCache().getAll().find(q=>q.queryKey[0]==='plugin-query'&&q.queryKey[3]==='probe.echo'&&q.queryKey[4]?.value===${JSON.stringify(value)})`;

 await s.navigate(`http://127.0.0.1:${server.address().port}/settings/query-proof`);await until(()=>s.eval("document.querySelector('[data-b]')?.textContent==='x'"),'B loaded');
 const before=requests.length;
 await s.eval("void window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['plugin-query','probe']})");
 await until(()=>requests.length>before,'the enabled consumer refetches');
 for(const ms of [300,800,1500]){await new Promise(r=>setTimeout(r,ms));
  assert.equal(await s.eval("document.querySelector('[data-b]').textContent"),'x','the enabled consumer keeps its result after an invalidation');
  assert.equal(await s.eval("document.querySelector('[data-a]').textContent"),'A ok');}
 checks.push('an invalidation refetches for the enabled consumer; the disabled one cannot fail it');
 const beforeRefetch=requests.length;await s.eval('void window.__A.refetch()');await new Promise(r=>setTimeout(r,500));
 assert.equal(requests.length,beforeRefetch,'a disabled consumer\'s refetch asks for nothing');
 assert.equal(await s.eval("document.querySelector('[data-b]').textContent"),'x','and does not break the shared result');
 checks.push('a disabled consumer\'s refetch neither fetches nor breaks the shared result');
 assert(!s.consoleErrors.some(e=>/Invalid hook|not exported|Maximum update depth/.test(e)));
 console.log(JSON.stringify({passed:true,checks}));
}finally{release?.();if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}

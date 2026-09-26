/** Exercise the actual Automations remote/chunks and SDK lifecycle in the built host. */
import assert from 'node:assert/strict';
import http from 'node:http';
import {existsSync,readFileSync,statSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import path from 'node:path';
import {openBrowser} from './lib/cdp.mjs';
const dist=new URL('../dist/',import.meta.url).pathname;
const enabled=new Set(['fixture','ai']);
let version=1,broken=false,hold=false,refuse=false,aborted=0;
const requests=[],releases=[];
const nodeSpec={key:'ai.classify',plugin:'ai',kind:'gate',label:'Classify fixture',description:'',group:'AI',params_schema:{},keywords:'',default_params:{},reads_event:false,produces_findings:false,dynamic_ports:true,dynamic_outputs:true,shape_params:['answers'],terminal:false,ports:[],default_ports:[],outputs:[],needs_items:false,permission:''};
const terminal={...nodeSpec,key:'verdict.block',plugin:'automations',kind:'action',label:'Block submission',terminal:true,dynamic_ports:false,dynamic_outputs:false};
const catalog={nodes:[nodeSpec,terminal],node_arity:[],triggers:[],trigger_kinds:[],tokens:[],schedule_kinds:[],operators:[],can_act_as:false,max_chain_depth:8};
const savedRule={id:'saved',name:'Saved canvas',enabled:false,version:2,orientation:'vertical',triggers:[],position:0,last_run_at:null,last_run_status:'',created_at:'2026-09-25T12:00:00Z',updated_at:'2026-09-25T12:00:00Z',nodes:[{id:'a',kind:'gate',type:'ai.classify',name:'answer',params:{answers:['alpha']},x:0,y:0},{id:'b',kind:'action',type:'verdict.block',params:{},x:0,y:200}],edges:[{source:'a',port:'alpha',target:'b'}]};
const oldVersion={id:'version-1',automation_id:'saved',version:1,name:'Older canvas',created_by_id:null,created_by_name:'Admin',created_at:'2026-09-24T12:00:00Z',note:'Older answers',restored_from:null,node_count:2,nodes:savedRule.nodes.map(n=>n.id==='a'?{...n,params:{answers:['historic']}}:n),edges:[{source:'a',port:'historic',target:'b'}],orientation:'vertical'};
const harness=`import{createElement as h,useState}from'react';import{definePlugin,SlotId,Slot,SettingsPage}from'@radd/plugin-sdk';
function Harness(){const[c,setC]=useState(${JSON.stringify(catalog)});const[readOnly,setReadOnly]=useState(false);const[second,setSecond]=useState(false);const[nodes,setNodes]=useState([{id:'a',kind:'gate',type:'ai.classify',name:'answer',params:{answers:['alpha']},x:0,y:0},{id:'b',kind:'action',type:'verdict.block',params:{},x:0,y:200}]);const[edges,setEdges]=useState([{source:'a',port:'alpha',target:'b'}]);
window.__canvasProof={setC,setReadOnly,setSecond,setNodes,nodes,edges};
const props={nodes,edges,catalog:c,readOnly,onNodesChange:n=>setNodes(n),onNodesDelete:ids=>{setNodes(n=>n.filter(x=>!ids.includes(x.id)));setEdges(e=>e.filter(x=>!ids.includes(x.source)&&!ids.includes(x.target)))},onEdgesDelete:removed=>setEdges(e=>e.filter(x=>!removed.some(r=>JSON.stringify(r)===JSON.stringify(x)))),onConnect:e=>setEdges(x=>[...x,e])};
return h(SettingsPage,{title:'Automation canvas proof'},h('div',{'data-canvas':'main'},h(Slot,{id:'automation.graph.canvas',...props,fallback:h('p',{},'Canvas unavailable'),errorFallback:h('p',{},'Canvas failed')})),second&&h('div',{'data-canvas':'second'},h(Slot,{id:'automation.graph.canvas',...props,readOnly:true,nodes:nodes.map(n=>n.id==='a'?{...n,params:{answers:['beta']}}:n)})));}
export default definePlugin({contributions:[{id:'proof',slot:SlotId.settingsPage,match:'/settings/automation-proof',render:()=>h(Harness)}]});`;
const server=http.createServer(async(req,res)=>{
 const p=new URL(req.url,'http://fixture').pathname;
 if(p.startsWith('/plugins/')){
  const [, ,name,...parts]=p.split('/');
  if(name==='fixture'){res.setHeader('content-type','text/javascript');res.end(harness);return;}
  const file=new URL(`../../server/src/radd/modules/${name}/ui/dist/${parts.join('/')}`,import.meta.url).pathname;
  if(broken||!existsSync(file)){res.writeHead(404);res.end();return;}
  res.setHeader('content-type',file.endsWith('.js')?'text/javascript':'text/css');res.end(readFileSync(file));return;
 }
 if(p.startsWith('/api/')){
  let data=[];
  if(p.endsWith('/auth/me'))data={id:'admin',name:'Admin',email:'admin@example.test',instance_role:'admin',global_role:'admin',permissions:['*']};
  else if(p.includes('capabilities'))data={capabilities:[],plugins:[...enabled],remotes:[...enabled].filter(n=>n!=='ai').map(name=>({name,remote_entry:`/plugins/${name}/remoteEntry.js?v=${version}`,ui_api_version:'1.4.0'})),nav:[{key:'automations',plugin:'automations',path:'/settings/automations',section:'settings',label:'Automations',requires:[]},{key:'fixture',plugin:'fixture',path:'/settings/automation-proof',section:'settings',label:'Canvas proof',requires:[]}],widget_types:[],view_types:[]};
  else if(p.endsWith('/automations/catalog'))data=catalog;
  else if(p.endsWith('/automations'))data=[savedRule];
  else if(p.endsWith('/automations/saved/versions'))data=[oldVersion];
  else if(p.endsWith('/automations/saved/versions/1'))data=oldVersion;
  else if(p.endsWith('/shape')){
   let body='';for await(const chunk of req)body+=chunk;
   const args=JSON.parse(body);requests.push({path:p,params:args.params});
   if(hold){res.on('close',()=>{if(!res.writableEnded)aborted++;});await new Promise(resolve=>releases.push(resolve));}
   if(refuse){res.writeHead(403,{'content-type':'application/json'});res.end(JSON.stringify({detail:'Shape access refused'}));return;}
   data={ports:[...(args.params.answers??[]),'unavailable'],outputs:[{name:'answer'}]};
  }
  else if(p.endsWith('/projects/summary')||p.endsWith('/page-spaces/summary'))data={total:0,related_count:0,permissions:[]};
  else if(p.includes('notifications'))data={items:[],notifications:[],unread_count:0,total:0};
  else if(p.includes('preferences'))data={};
  res.setHeader('content-type','application/json');res.end(JSON.stringify(data));return;
 }
 const file=path.join(dist,p),target=existsSync(file)&&statSync(file).isFile()?file:path.join(dist,'index.html');
 res.setHeader('content-type',target.endsWith('.js')?'text/javascript':target.endsWith('.css')?'text/css':'text/html');res.end(readFileSync(target));
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
let browser;const checks=[];
try{
 browser=await openBrowser({port:18832,profile:await mkdtemp('/tmp/radd-canvas-'),scale:1});const s=browser.session;
 const until=async(fn,label)=>{for(let i=0;i<250;i++){if(await fn())return;await new Promise(r=>setTimeout(r,40));}throw Error(label+': '+await s.eval('document.body.innerText')+' '+JSON.stringify(s.consoleErrors));};
 const ev=code=>s.eval(`(()=>{${code}})()`);
 const text=t=>s.eval(`document.body.innerText.includes(${JSON.stringify(t)})`);
 const handles=which=>s.eval(`Array.from(document.querySelectorAll('[data-canvas="${which}"] [data-node-id="a"] .source')).map(e=>e.getAttribute('data-handleid'))`);
 const change=async fn=>{fn();await s.eval(`window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['capabilities']})`);};
 const params=answers=>ev(`window.__canvasProof.setNodes(ns=>ns.map(n=>n.id==='a'?{...n,params:{answers:${JSON.stringify(answers)}}}:n));`);
 await s.navigate(`http://127.0.0.1:${server.address().port}/settings/automation-proof`);
 await until(()=>text('Canvas unavailable'),'initially unavailable');assert.equal(requests.length,0);checks.push('initially absent Automations makes no shape requests');
 await change(()=>enabled.add('automations'));
 await until(async()=>(await handles('main')).includes('unavailable'),'actual remote resolves ports');
 assert.equal(requests.length,1);assert.deepEqual(await handles('main'),['alpha','unavailable']);
 assert.equal(await s.eval(`document.querySelectorAll('[data-node-id="b"] .source').length`),0);
 await until(()=>s.eval(`Array.from(document.querySelectorAll('[data-canvas="main"] .react-flow__node')).every(n=>getComputedStyle(n).visibility==='visible')`),'React Flow measurements settle');
 const style=await s.eval(`(()=>{const n=document.querySelector('[data-node-id="a"]');const f=n.closest('.react-flow');return {width:n.getBoundingClientRect().width,height:f.getBoundingClientRect().height,visible:getComputedStyle(n.closest('.react-flow__node')).visibility,position:getComputedStyle(f.querySelector('.react-flow__viewport')).position,inlet:getComputedStyle(n.querySelector('.target')).backgroundColor}})()`);
 assert(style.width>180&&style.height===620-2,JSON.stringify(style));assert.equal(style.visible,'visible');assert.equal(style.position,'absolute');assert.notEqual(style.inlet,'rgba(0, 0, 0, 0)');
 const contrast=()=>s.eval(`(()=>{const el=document.querySelector('.react-flow__controls-button'),style=getComputedStyle(el),ctx=document.createElement('canvas').getContext('2d');function lum(color){ctx.fillStyle=color;ctx.fillRect(0,0,1,1);return [...ctx.getImageData(0,0,1,1).data].slice(0,3).map(c=>{c/=255;return c<=.04045?c/12.92:((c+.055)/1.055)**2.4}).reduce((sum,c,i)=>sum+c*[.2126,.7152,.0722][i],0)}const a=lum(style.color),b=lum(style.backgroundColor);return(Math.max(a,b)+.05)/(Math.min(a,b)+.05)})()`);
 assert(await contrast()>=4.5,'dark canvas controls contrast');await ev("document.documentElement.classList.add('light');");assert(await contrast()>=4.5,'light canvas controls contrast');await ev("document.documentElement.classList.remove('light');");
 await s.screenshot('/tmp/radd-automation-canvas.png');checks.push('actual lazy chunk/CSS renders measured visible nodes, terminal ports and themed handles');
 await ev('window.__canvasProof.setSecond(true);');await until(async()=>(await handles('second')).includes('beta'),'independent preview resolves');assert.deepEqual(await handles('main'),['alpha','unavailable']);checks.push('two graph consumers keep different dynamic shapes isolated');
 await ev('window.__canvasProof.setSecond(false);');
 hold=true;await params(['held']);await until(()=>releases.length===1,'shape request pending');
 await params(['fresh']);await until(()=>aborted>0,'edited request aborted');hold=false;for(const release of releases.splice(0))release();
 await until(async()=>(await handles('main')).includes('fresh'),'new params resolved');assert(!(await handles('main')).includes('held'));checks.push('changing params aborts obsolete shape requests and suppresses late results');
 hold=true;await params(['withdrawn']);await until(()=>releases.length===1,'provider request held');const previous=aborted;
 await change(()=>enabled.delete('ai'));await until(()=>aborted>previous,'provider withdrawal aborts');
 assert.deepEqual(await handles('main'),['alpha']);assert(await text('Ports not resolved'));
 assert.equal(await s.eval(`document.querySelector('[data-node-id="a"] .source').classList.contains('connectable')`),false);
 assert.equal(await s.eval('window.__canvasProof.edges.length'),1);assert.equal(await s.eval('window.__canvasProof.nodes.length'),2);
 hold=false;for(const release of releases.splice(0))release();const requestCount=requests.length;await new Promise(r=>setTimeout(r,350));assert.equal(requests.length,requestCount);
 checks.push('dependent provider withdrawal stops queries despite retained catalog; saved nodes/edges survive with nonconnectable handles');
 await change(()=>enabled.add('ai'));await until(async()=>(await handles('main')).includes('withdrawn'),'provider restored');checks.push('provider re-enable gets a fresh shape');
 hold=true;await params(['canvas-held']);await until(()=>releases.length===1,'canvas request held');const canvasAborts=aborted;
 await change(()=>enabled.delete('automations'));await until(()=>text('Canvas unavailable'),'withdraw while query is in flight');await until(()=>aborted>canvasAborts,'canvas unmount aborts');
 hold=false;for(const release of releases.splice(0))release();assert.equal(await s.eval('window.__canvasProof.nodes.length'),2);
 await change(()=>enabled.add('automations'));await until(async()=>(await handles('main')).includes('canvas-held'),'canvas restores fresh shape');checks.push('withdrawing Automations aborts its in-flight work and re-enable resolves preserved params');
 refuse=true;await params(['denied']);await until(()=>requests.at(-1)?.params.answers?.[0]==='denied','refused shape requested');await until(()=>s.eval(`window.__RADD_QUERY_CLIENT__.getQueryCache().findAll({queryKey:['automation-node-shape']}).some(q=>q.state.status==='error')`),'refusal received');assert(await text('Ports not resolved'));
 assert.deepEqual(await handles('main'),['alpha']);refuse=false;await params(['permitted']);await until(async()=>(await handles('main')).includes('permitted'),'shape recovered');checks.push('refused shape cannot reuse previous answers and subsequent valid params recover');
 await ev(`window.__canvasProof.setC(c=>({...c,nodes:c.nodes.map(n=>n.key==='ai.classify'?{...n,label:'Replacement label',dynamic_ports:false,dynamic_outputs:false,ports:['replacement']}:n)}));`);
 await until(async()=>await text('Replacement label')&&(await handles('main')).includes('replacement'),'same-sized catalog refreshed');checks.push('same-sized catalog replacement updates labels and ports');
 await ev(`window.__canvasProof.setNodes(ns=>ns.map(n=>n.id==='a'?{...n,kind:'filter',params:{condition:'Owner-defined predicate'}}:n));`);
 await until(()=>text('condition: Owner-defined predicate'),'contributed filter keeps its semantics');assert(!await text('matches everything'));checks.push('contributed filter kind does not inherit the built-in SLQ summary');
 await ev('window.__canvasProof.setReadOnly(true);');await until(()=>s.eval(`!document.querySelector('[data-canvas="main"] .react-flow__node').classList.contains('draggable')`),'read-only update');
 await s.click('[data-canvas="main"] [data-node-id="a"]');await s.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Delete',code:'Delete',windowsVirtualKeyCode:46});await s.send('Input.dispatchKeyEvent',{type:'keyUp',key:'Delete',code:'Delete',windowsVirtualKeyCode:46});
 await new Promise(r=>setTimeout(r,100));assert.equal(await s.eval(`document.querySelectorAll('[data-canvas="main"] .react-flow__node').length`),2);assert.equal(await s.eval('window.__canvasProof.nodes.length'),2);checks.push('switching read-only updates drag affordance and Delete cannot remove preview nodes');
 await ev('window.__canvasProof.setReadOnly(false);');await until(()=>s.eval(`document.querySelector('[data-canvas="main"] .react-flow__node').classList.contains('draggable')`),'editing restored');
 await s.click('[data-canvas="main"] [data-node-id="a"]');await s.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Delete',code:'Delete',windowsVirtualKeyCode:46});await s.send('Input.dispatchKeyEvent',{type:'keyUp',key:'Delete',code:'Delete',windowsVirtualKeyCode:46});
 await until(()=>s.eval('window.__canvasProof.nodes.length===1'),'delete callback reaches graph');assert.equal(await s.eval('window.__canvasProof.edges.length'),0);checks.push('editable Delete updates parent graph and removes incident wires');
 await change(()=>enabled.delete('automations'));await until(()=>text('Canvas unavailable'),'canvas withdrawal');const count=requests.length;
 await change(()=>enabled.add('automations'));await until(()=>s.eval(`document.querySelectorAll('[data-canvas="main"] .react-flow').length===1`),'one canvas restored');assert.equal(requests.length,count);assert.equal(await s.eval('window.__canvasProof.nodes.length'),1);checks.push('Automations withdrawal/re-enable restores one canvas without modifying saved content');
 await change(()=>{broken=true;version++;});await until(()=>text('Canvas unavailable'),'failed remote falls back');
 await change(()=>{broken=false;version++;});await until(()=>s.eval(`document.querySelectorAll('[data-canvas="main"] .react-flow').length===1`),'remote recovered');checks.push('failed remote remains unavailable and a new version recovers');
 const beforeHost=requests.length;
 await s.navigate(`http://127.0.0.1:${server.address().port}/settings/automations`);await until(()=>text('Saved canvas'),'owner settings list');
 await s.click('[aria-label="Edit Saved canvas"]');await until(()=>s.eval(`document.querySelector('[data-node-id="a"] [data-handleid="alpha"]')!==null`),'owner editor uses actual remote');
 assert.equal(requests.length,beforeHost+1,'host shape results supplied to canvas without a duplicate query');
 await until(()=>s.eval(`getComputedStyle(document.querySelector('[data-node-id="a"]').closest('.react-flow__node')).visibility==='visible'`),'host node visible');
 await s.click('[data-node-id="a"]');await until(()=>text('answer.answer'),'inspector receives dynamic outputs');
 await s.click('button',t=>t.trim()==='Versions');await until(()=>s.eval(`document.querySelector('[data-version-row="1"] button')!==null`),'versions list');
 await s.click('[data-version-row="1"] button');await until(()=>s.eval(`document.querySelector('[data-version-preview="1"] [data-handleid="historic"]')!==null`),'actual VersionsPanel resolves its own historical shape');
 assert(await s.eval(`document.querySelector('[data-node-id="a"] [data-handleid="alpha"]')!==null`));
 await s.screenshot('/tmp/radd-automation-editor-owned.png');checks.push('owner editor supplies shapes to remote and inspector; actual VersionsPanel resolves independent historical ports');
 assert(!s.consoleErrors.some(e=>e.includes('Invalid hook')||e.includes('not exported')||e.includes('Maximum update depth')));
 console.log(JSON.stringify({passed:true,checks,requests:requests.length,aborted}));
}finally{for(const release of releases)release();if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}

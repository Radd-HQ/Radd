/** Generic page lifecycle, render isolation and SDK capability sharing (RADD-1351). */
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {openBrowser,until} from './lib/cdp.mjs';
import {serveBuiltSpa} from './lib/spa-server.mjs';
let mode='good', enabled=true, version=1, remoteRead=0;
let release;
const spa=await serveBuiltSpa(async(req,res,url)=>{
 const p=url.pathname;
 if(p==='/plugins/fixture/remoteEntry.js') {
  remoteRead++;
  if(mode==='delayed') await new Promise(resolve=>{release=resolve;});
  if(mode==='missing'){res.writeHead(404);res.end();return true;}
  const body=mode==='throws'?'throw Error("render callback failed")':mode==='child-throws'?'return h(Broken)':'return h("div",null,h("h2",null,"Contributed settings"),h("p",null,"Feature available: "+useHasPlugin("feature")))';
  res.setHeader('content-type','text/javascript');
  res.end(`import {createElement as h} from 'react'; import {definePlugin,SlotId,useHasPlugin} from '@radd/plugin-sdk'; function Broken(){throw Error('child failed')} export default definePlugin({contributions:[{id:'page',slot:SlotId.settingsPage,match:'/settings/fixture',render:()=>{${body}}}]});`);return true;
 }
 if(p.startsWith('/api/')) {
  let data=[];
  if(p.endsWith('/auth/me'))data={id:'admin',name:'Admin',email:'admin@example.test',global_role:'admin',instance_role:'admin',permissions:['*']};
  else if(p.includes('capabilities'))data={capabilities:[],nav:enabled?[{key:'fixture',plugin:'fixture',path:'/settings/fixture',label:'Fixture',section:'settings',group:'Server',requires:[],icon:'activity'}]:[],plugins:enabled?['fixture',...(version===1?['feature']:[])]:[],remotes:enabled?[{name:'fixture',remote_entry:`/plugins/fixture/remoteEntry.js?v=${version}`,ui_api_version: '2.0.0'}]:[],widget_types:[],view_types:[]};
  else if(p.endsWith('/projects/summary')||p.endsWith('/page-spaces/summary'))data={total:0,related_count:0,permissions:[]};
  else if(p.includes('notifications'))data={items:[],notifications:[],unread_count:0,total:0};
  else if(p.includes('preferences'))data={};
  res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify(data));return true;
 }
});
let browser;
try {
 browser=await openBrowser({port:18829,profile:await mkdtemp('/tmp/radd-plugin-pages-'),scale:1});
 const s=browser.session,base=spa.origin;
 const text=t=>s.eval(`document.body.innerText.includes(${JSON.stringify(t)})`);
 const refresh=()=>s.eval(`window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['capabilities']})`);
 await s.navigate(base+'/settings/fixture');
 await until(s,()=>text('Feature available: true'),'page renders');
 assert(await s.eval(`Array.from(document.querySelectorAll('section[aria-label="Server"] a')).some(a=>a.textContent.includes('Fixture'))`));
 version++; await refresh();
 await until(s,()=>text('Feature available: false'),'SDK sees capability withdrawal in host cache');
 enabled=false;await refresh();
 await until(s,()=>text('This page is unavailable.'),'disabled route is explicit');
 assert(!await text('Contributed settings'));
 enabled=true;mode='missing';version++;await refresh();
 await until(s,()=>text('This plugin page could not be loaded.'),'failed import is explicit');
 for(const next of ['throws','child-throws']){
  mode=next;version++;await refresh();
  await until(s,()=>remoteRead>=version,'replacement requested');
  await until(s,()=>text('This plugin page could not be loaded.'),'throw isolated');
  assert(await s.eval(`document.querySelector('nav[aria-label="Settings sections"]') !== null`));
 }
 mode='delayed';version++;await refresh();
 await until(s,()=>text('Loading plugin page…'),'pending bundle shows loading');
 release();mode='good';
 await until(s,()=>text('Contributed settings'),'page recovers after prior render failure');
 await s.screenshot('/tmp/radd-plugin-page-recovered.png');
 console.log(JSON.stringify({passed:true,checks:['manifest navigation grouping','SDK shares live capabilities','disabled route fallback','failed import fallback','render callback boundary','child component boundary','loading state','recovery on new registration']}));
}finally{release?.();if(browser)await browser.close();await spa.close();}

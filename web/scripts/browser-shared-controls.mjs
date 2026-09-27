/** Generic controls exercised in the actual host and actual Scripts/AI remote inspectors. */
import assert from 'node:assert/strict';
import {readFileSync,readdirSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import path from 'node:path';
import {openBrowser,until} from './lib/cdp.mjs';
import {DIST,serveBuiltSpa} from './lib/spa-server.mjs';
const languageBundle=readdirSync(path.join(DIST,'assets')).find(name=>name.startsWith('code-languages-'));
assert(languageBundle,'built language catalog');
const rustChunk=readFileSync(path.join(DIST,'assets',languageBundle),'utf8').match(/name:`Rust`[\s\S]*?import\(`\.\/([^`]+)`\)/)?.[1];
assert(rustChunk,'Rust grammar import in built catalog');
const enabled=new Set(['fixture']),broken=new Set(),versions={fixture:1,scripts:1,ai:1};
let holdGrammar=false,releaseGrammar,scriptRuns=0;
const schema={type:'object',required:['count','rank','flag'],properties:{title:{type:'string',title:'Short text',maxLength:5},rank:{type:'integer',title:'Rank',enum:[1,2]},flag:{type:'boolean',title:'Flag',enum:[false,true]},mode:{type:'string',title:'Mode',enum:['fast','slow']},count:{type:'integer',title:'Count',minimum:1,maximum:10},options:{type:'object',title:'Context',properties:{summary:{type:'boolean',title:'Summary',default:true},comments:{type:'boolean',title:'Comments'}}},nested:{type:'object',title:'Structured setting',properties:{name:{type:'string'}}}}};
const harness=`import{createElement as h,useState}from'react';import{definePlugin,SlotId,Slot,SettingsPage,CodeEditor,SchemaForm,defaultsFromSchema}from'@radd/plugin-sdk';
const schema=${JSON.stringify(schema)};
function Harness(){const[tab,setTab]=useState('schema');const[params,setParams]=useState({title:'saved',rank:1,flag:false,mode:'fast',count:7,options:'legacy',nested:{name:'keep',extra:[1,2]},unlisted:{untouched:true}});const[code,setCode]=useState('const answer = true;');const[language,setLanguage]=useState('javascript');const[revision,setRevision]=useState(0);const[readOnly,setReadOnly]=useState(false);const[changes,setChanges]=useState([]);const[script,setScript]=useState({body:'def main(ctx):\\n    return {}',timeout:30,outputs:['answer'],custom:'retained'});const[ai,setAi]=useState({prompt:'original prompt',include:{summary:true,comments:false},fields:[{name:'priority',kind:'text',description:'Keep this field',choices:[]}]});
window.__controls={setTab,setParams,params,setCode,code,setLanguage,setRevision,setReadOnly,changes,setScript,script,setAi,ai,defaults:defaultsFromSchema(schema)};
return h(SettingsPage,{title:'Shared control proof'},h('div',{'data-control':tab},tab==='schema'?h(SchemaForm,{schema,params,onChange:setParams}):tab==='code'?h(CodeEditor,{value:code,language,readOnly,ariaLabel:'Example code',minHeight:200,onChange:value=>{setChanges(c=>[...c,{revision,value}]);setCode(value)}}):tab==='scripts'?h(Slot,{id:SlotId.automationNodeInspector,match:'script.run',params:script,onChange:setScript,fallback:h('p',{},'Scripts unavailable')}):h(Slot,{id:SlotId.automationNodeInspector,match:'ai.generate',node:{type:'ai.generate',params:ai},params:ai,onChange:setAi,schema:{type:'object',properties:{prompt:{type:'string',title:'Prompt'},include:{type:'object',title:'Include',properties:{summary:{type:'boolean',title:'Summary',default:true},comments:{type:'boolean',title:'Comments'}}},fields:{type:'array'}}},fallback:h('p',{},'AI unavailable')})));}
export default definePlugin({contributions:[{id:'controls-proof',slot:SlotId.settingsPage,match:'/settings/controls-proof',render:()=>h(Harness)}]});`;
const spa=await serveBuiltSpa(async(req,res,url)=>{
 const p=url.pathname;
 if(p.startsWith('/plugins/')){
  const name=p.split('/')[2];if(broken.has(name)){res.writeHead(404);res.end();return true;}
  if(name==='fixture'){res.setHeader('content-type','text/javascript');res.end(harness);return true;}
  return false;
 }
 if(p.startsWith('/api/')){
  let data=[];
  if(p.endsWith('/auth/me'))data={id:'admin',name:'Admin',email:'admin@example.test',instance_role:'admin',global_role:'admin',permissions:['*']};
  else if(p.includes('capabilities'))data={capabilities:[],plugins:[...enabled],remotes:[...enabled].map(name=>({name,remote_entry:`/plugins/${name}/remoteEntry.js?v=${versions[name]}`,ui_api_version: '2.0.0'})),nav:[{key:'fixture',plugin:'fixture',path:'/settings/controls-proof',section:'settings',label:'Controls proof',requires:[]}],widget_types:[],view_types:[]};
  else if(p.endsWith('/projects/summary')||p.endsWith('/page-spaces/summary'))data={total:0,related_count:0,permissions:[]};
  else if(p.includes('notifications'))data={items:[],notifications:[],unread_count:0,total:0};
  else if(p.includes('preferences'))data={};
  else if(p.endsWith('/scripts/run')){scriptRuns++;data={ok:true,result:{answer:'fixture'},duration_ms:1};}
  res.setHeader('content-type','application/json');res.end(JSON.stringify(data));return true;
 }
 if(holdGrammar&&path.basename(p)===rustChunk)await new Promise(resolve=>{releaseGrammar=resolve;});
});
let browser;const checks=[];
try{
 browser=await openBrowser({port:18833,profile:await mkdtemp('/tmp/radd-shared-controls-'),scale:1});const s=browser.session;
 const ev=code=>s.eval(`(()=>{${code}})()`),text=t=>s.eval(`document.body.innerText.includes(${JSON.stringify(t)})`);
 const tab=async name=>{await ev(`window.__controls.setTab(${JSON.stringify(name)})`);await until(s,()=>s.eval(`document.querySelector('[data-control="${name}"]')!==null`),'tab '+name);};
 const input=async(label,value)=>ev(`const label=Array.from(document.querySelectorAll('[data-control] label')).find(e=>e.textContent.trim()===${JSON.stringify(label)});const el=document.getElementById(label.htmlFor);Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,${JSON.stringify(value)});el.dispatchEvent(new Event('input',{bubbles:true}));`);
 const option=async(label,value)=>{
  const id=await ev(`return Array.from(document.querySelectorAll('[data-control] label')).find(e=>e.textContent.trim()===${JSON.stringify(label)}).htmlFor;`);
  await s.click(`[id=${JSON.stringify(id)}]`);
  await until(s,()=>s.eval(`document.querySelector('[role="option"]')!==null`),'options opened');
  await s.click('[role="option"]',new Function('t',`return t.trim()===${JSON.stringify(value)}`));
 };
 const change=async fn=>{fn();await s.eval(`window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:['capabilities']})`);};
 const keyword=word=>s.eval(`Array.from(document.querySelectorAll('[data-code-editor] .cm-line span')).some(e=>e.textContent===${JSON.stringify(word)})`);
 await s.navigate(`${spa.origin}/settings/controls-proof`);await until(s,()=>text('Structured setting'),'generic schema form');
 assert.equal(await s.eval('window.__controls.params.options'),'legacy');assert.equal(await s.eval(`document.querySelector('[data-schema-check="summary"]').checked`),true);
 await option('Rank','2');assert.equal(await s.eval('typeof window.__controls.params.rank'),'number');assert.equal(await s.eval('window.__controls.params.rank'),2);
 await option('Flag','true');assert.equal(await s.eval('window.__controls.params.flag'),true);
 await option('Mode','—');assert.equal(await s.eval(`Object.hasOwn(window.__controls.params,'mode')`),false);checks.push('SDK form works without automation plugin; enums preserve types and optional clearing removes value');
 await input('Count','');assert.equal(await s.eval(`Object.hasOwn(window.__controls.params,'count')`),false);await input('Count','4');assert.equal(await s.eval('window.__controls.params.count'),4);
 assert.equal(await s.eval(`Array.from(document.querySelectorAll('label')).find(e=>e.textContent==='Short text').parentElement.querySelector('input').maxLength`),5);checks.push('empty number is missing rather than zero; schema length limit is applied');
 await s.click('[data-schema-check="comments"]');assert.deepEqual(await s.eval('window.__controls.params.options'),{summary:true,comments:true});
 await input('Short text','new');assert.deepEqual(await s.eval('window.__controls.params.nested'),{name:'keep',extra:[1,2]});assert.deepEqual(await s.eval('window.__controls.params.unlisted'),{untouched:true});assert.equal(await s.eval(`document.querySelector('[data-schema-unsupported="nested"]').querySelectorAll('input').length`),0);checks.push('boolean groups repair only on user edit; unsupported and unlisted structured values survive edits');
 await ev(`window.__controls.setParams(p=>({...p,rank:99}));`);await until(s,()=>text('Saved value: 99'),'unknown saved enum visible');await input('Count','5');assert.equal(await s.eval('window.__controls.params.rank'),99);checks.push('unrecognized saved enum remains visible and preserved');
 await tab('code');await until(s,()=>keyword('const'),'JavaScript grammar selected');assert.equal(await s.eval(`document.querySelector('[aria-label="Example code"]').getAttribute('contenteditable')`),'true');checks.push('generic CodeEditor honors JavaScript without Scripts installed');
 for(const theme of ['dark','light']){
  await ev(`document.documentElement.classList.toggle('light',${theme==='light'});`);
  const styles=await ev(`const gutter=document.querySelector('[data-code-editor] .cm-gutters');const probe=document.createElement('span');probe.style.backgroundColor='var(--color-surface)';document.body.append(probe);const expected=getComputedStyle(probe).backgroundColor;probe.remove();return {gutter:getComputedStyle(gutter).backgroundColor,expected,height:document.querySelector('[data-code-editor] .cm-editor').getBoundingClientRect().height};`);
  assert.equal(styles.gutter,styles.expected);assert(styles.height>=200);
 }
 await ev("document.documentElement.classList.remove('light')");
 checks.push('editor respects requested height and gutter theme in dark and light');
 await ev(`window.__controls.setRevision(1);`);await s.click('[data-code-editor] .cm-content');await s.send('Input.insertText',{text:'x'});await until(s,()=>s.eval('window.__controls.changes.length===1'),'one edit callback');assert.equal(await s.eval('window.__controls.changes[0].revision'),1);
 await ev(`window.__controls.setCode('def greet():\\n    return True');window.__controls.setLanguage('python');`);await until(s,()=>keyword('def'),'Python grammar selected');assert.equal(await s.eval('window.__controls.changes.length'),1);checks.push('latest callback is used; external value/language updates do not echo as edits');
 await ev(`window.__controls.setReadOnly(true);`);await until(s,()=>s.eval(`document.querySelector('[data-code-editor] .cm-content').getAttribute('contenteditable')==='false'`),'read-only input');assert.equal(await s.eval('window.__controls.changes.length'),1);await ev(`window.__controls.setReadOnly(false);`);
 holdGrammar=true;await ev(`window.__controls.setCode('fn main() {}');window.__controls.setLanguage('rust');`);await until(s,()=>Boolean(releaseGrammar),'Rust grammar held');await ev(`window.__controls.setLanguage('');`);holdGrammar=false;releaseGrammar();releaseGrammar=undefined;await new Promise(r=>setTimeout(r,300));assert.equal(await keyword('fn'),false);checks.push('read-only changes live; a late grammar cannot override a newer language choice');
 await s.screenshot('/tmp/radd-generic-code-editor.png');
 await tab('scripts');await until(s,()=>text('Scripts unavailable'),'initially absent script inspector');assert.equal(scriptRuns,0);
 await change(()=>enabled.add('scripts'));await until(s,()=>s.eval(`document.querySelector('[data-script-node] [data-code-editor] .cm-content')!==null`),'actual Scripts inspector');await until(s,()=>keyword('def'),'Scripts chooses Python');
 await input('Timeout (seconds)','91');await s.click('[data-script-node] .cm-content');await s.send('Input.insertText',{text:'x'});await until(s,()=>s.eval(`window.__controls.script.body.includes('x')`),'script edited');assert.equal(await s.eval('window.__controls.script.timeout'),91);assert.equal(await s.eval('window.__controls.script.custom'),'retained');checks.push('actual Scripts inspector preserves changed timeout and other params when code is edited');
 const savedScript=await s.eval('window.__controls.script');await change(()=>enabled.delete('scripts'));await until(s,()=>text('Scripts unavailable'),'Scripts withdrawn');assert.equal(await s.eval(`document.querySelectorAll('[data-code-editor]').length`),0);await change(()=>enabled.add('scripts'));await until(s,()=>s.eval(`document.querySelectorAll('[data-code-editor]').length===1`),'Scripts restored');assert.deepEqual(await s.eval('window.__controls.script'),savedScript);assert.equal(scriptRuns,0);checks.push('Scripts withdrawal destroys editor; re-enable restores one editor with preserved draft and no execution');
 await change(()=>{broken.add('scripts');versions.scripts++;});await until(s,()=>text('Scripts unavailable'),'failed Scripts remote');await change(()=>{broken.delete('scripts');versions.scripts++;});await until(s,()=>s.eval(`document.querySelectorAll('[data-code-editor]').length===1`),'Scripts recovered');checks.push('failed Scripts remote recovers without losing the controlled draft');
 await tab('ai');await until(s,()=>text('AI unavailable'),'initially absent AI');await change(()=>enabled.add('ai'));await until(s,()=>text('VALUES TO PRODUCE'),'actual AI generator');
 await input('Prompt','changed prompt');await s.click('[data-schema-check="comments"]');assert.equal(await s.eval('window.__controls.ai.prompt'),'changed prompt');assert.equal(await s.eval('window.__controls.ai.include.comments'),true);assert.equal(await s.eval('window.__controls.ai.fields[0].description'),'Keep this field');checks.push('actual AI inspector consumes SDK schema controls while preserving its owned output fields');
 const savedAi=await s.eval('window.__controls.ai');await change(()=>enabled.delete('ai'));await until(s,()=>text('AI unavailable'),'AI withdrawn');await change(()=>enabled.add('ai'));await until(s,()=>text('VALUES TO PRODUCE'),'AI restored');assert.deepEqual(await s.eval('window.__controls.ai'),savedAi);assert.equal(await s.eval(`document.querySelectorAll('[data-generate-fields]').length`),1);checks.push('AI withdrawal/re-enable preserves draft without duplicate forms');
 await s.screenshot('/tmp/radd-sdk-schema-ai.png');
 assert(!s.consoleErrors.some(e=>e.includes('Invalid hook')||e.includes('not exported')||e.includes('Maximum update depth')));
 console.log(JSON.stringify({passed:true,checks,scriptRuns}));
}finally{releaseGrammar?.();if(browser)await browser.close();await spa.close();}

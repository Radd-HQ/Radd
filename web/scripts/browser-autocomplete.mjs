/** Real React hook + real HTTP: obsolete SLQ suggestions abort at every lifecycle boundary. */
import assert from 'node:assert/strict';
import http from 'node:http';
import {readFile,writeFile,mkdtemp} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {build} from '../node_modules/rolldown/dist/index.mjs';
import {openBrowser} from './lib/cdp.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));
const temp=await mkdtemp('/tmp/radd-autocomplete-');
const entry=path.join(temp,'entry.js');
const bundle=path.join(temp,'bundle.js');
await writeFile(entry,`
import {createElement as h,useState} from ${JSON.stringify(path.join(root,'node_modules/react/index.js'))};
import {createRoot} from ${JSON.stringify(path.join(root,'node_modules/react-dom/client.js'))};
import {useSlqAutocomplete} from ${JSON.stringify(path.join(root,'src/lib/useSlqAutocomplete.ts'))};
function Suggestions(){
 const [project,setProject]=useState('A');
 const [dialect,setDialect]=useState('/items');
 const suggestions=useSlqAutocomplete({project_id:project},dialect);
 return h('section',null,
  h('input',{id:'query','aria-label':'Query',onChange:e=>suggestions.request(e.target.value,e.target.value.length,true)}),
  h('button',{id:'close',onClick:suggestions.close},'Close suggestions'),
  h('button',{id:'scope',onClick:()=>setProject('B')},'Change project'),
  h('button',{id:'dialect',onClick:()=>setDialect('/timesheet')},'Change dialect'),
  h('div',{id:'state'},suggestions.open?'open':'closed'));
}
function App(){const [mounted,setMounted]=useState(true);return h('main',null,
 h('button',{id:'unmount',onClick:()=>setMounted(false)},'Leave editor'),mounted&&h(Suggestions));}
createRoot(document.getElementById('root')).render(h(App));
`);
await build({input:entry,platform:'browser',transform:{define:{'process.env.NODE_ENV':'"production"'}},output:{file:bundle}});
const started=new Map();const aborted=new Set();
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,'http://local');
 if(url.pathname.endsWith('/slq/suggest')){
  const q=url.searchParams.get('q');started.set(q,url);
  res.on('close',()=>{if(!res.writableEnded)aborted.add(q);});return;
 }
 res.writeHead(200,{'content-type':url.pathname==='/bundle.js'?'text/javascript':'text/html'});
 res.end(url.pathname==='/bundle.js'?await readFile(bundle):'<div id="root"></div><script type="module" src="/bundle.js"></script>');
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
let browser;
const until=async(predicate,label)=>{for(let i=0;i<100;i++){if(await predicate())return;await new Promise(r=>setTimeout(r,30));}throw Error(label);};
try{
 browser=await openBrowser({port:18802,profile:await mkdtemp('/tmp/radd-autocomplete-profile-'),scale:1});
 const s=browser.session;
 await s.navigate('http://127.0.0.1:'+server.address().port);
 const type=async text=>{
  await s.click('#query');await s.eval(`document.querySelector('#query').select()`);
  await s.send('Input.insertText',{text});
  await until(()=>started.has(text),'request did not start: '+text);
 };
 await type('superseded');await type('dismissed');
 await until(()=>aborted.has('superseded'),'new input kept old request alive');
 await s.click('#close');await until(()=>aborted.has('dismissed'),'dismissal kept request alive');
 await type('old-scope');await s.click('#scope');await until(()=>aborted.has('old-scope'),'scope change kept request alive');
 await type('old-dialect');assert.equal(started.get('old-dialect').searchParams.get('project_id'),'B');
 await s.click('#dialect');await until(()=>aborted.has('old-dialect'),'dialect change kept request alive');
 await type('unmounted');assert.equal(started.get('unmounted').pathname,'/api/v1/timesheet/slq/suggest');
 await s.click('#unmount');await until(()=>aborted.has('unmounted'),'unmount kept request alive');
 assert.equal(s.consoleErrors.length,0,s.consoleErrors.join('\n'));
 console.log('SLQ autocomplete: typing, close, project/dialect changes and unmount abort actual HTTP requests.');
} finally {browser?.close();server.close();}

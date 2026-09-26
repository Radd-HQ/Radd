/** Built SPA proof: package management, live application and actionable failures. */
import assert from 'node:assert/strict';
import { mkdtemp, writeFile } from 'node:fs/promises';
import { openBrowser, outputPath, until } from './lib/cdp.mjs';
import { serveBuiltSpa } from './lib/spa-server.mjs';
const plugin = {id:'acme-tools',name:'acme-tools',version:'0.1.0',core:false,state:'installed',
  description:'Company extension',can_toggle:true,capabilities:[],active:false,runtime_state:'disabled',pending_processes:0,runtime_errors:[],
  origin:'package',dependencies:[],problems:[]};
let failDisable = false;
let uploaded = null;
const spa = await serveBuiltSpa(async (req,res,url) => {
  const p = url.pathname;
  if(p.startsWith('/api/')) {
    let data = [];
    if(p.endsWith('/auth/me')) data={id:'admin',name:'Administrator',email:'admin@example.com',instance_role:'admin',permissions:['global.manage'],timezone:'UTC'};
    else if(p === '/api/v1/plugins') data=[plugin];
    else if(p.endsWith('/plugins/packages/upload')) {
      const chunks=[]; for await (const chunk of req) chunks.push(chunk);
      uploaded={body:Buffer.concat(chunks),type:req.headers['content-type']};
      data={id:plugin.id};
    }
    else if(p.endsWith('/plugins/acme-tools/install')) data=[plugin];
    else if(p.endsWith('/plugins/acme-tools/enable')) {plugin.state='enabled';plugin.runtime_state='applying';plugin.pending_processes=1;data=[plugin];}
    else if(p.endsWith('/plugins/acme-tools/disable')) {
      if(failDisable) {res.writeHead(409,{'content-type':'application/json'});res.end(JSON.stringify({detail:'Required by dependent-plugin'}));return true;}
      plugin.state='disabled';plugin.runtime_state='disabled';plugin.pending_processes=0;data=[plugin];
    }
    else if(p.endsWith('/projects/summary')) data={total:0,related_count:0,permissions:[]};
    else if(p.endsWith('/page-spaces/summary')) data={total:0,permissions:[]};
    else if(p.includes('capabilities')) data={capabilities:[],nav:[],plugins:[],ui:[]};
    else if(p.includes('notifications')) data={items:[],notifications:[],unread_count:0,total:0};
    else if(p.includes('preferences')) data={};
    else if(p.endsWith('/instance')) data={work_week_days:['mon'],timelog_hours_per_day:8,timelog_days_per_week:5};
    res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify(data));return true;
  }
});
let browser;
try {
  browser=await openBrowser({port:18824,profile:await mkdtemp('/tmp/radd-plugin-proof-'),scale:1});
  const s=browser.session;
  await s.navigate(`${spa.origin}/settings/plugins`);
  const see=text=>until(s,`document.body.innerText.includes(${JSON.stringify(text)})`,`Missing ${text}`);
  await see('Company extension');
  const wheelFile=(await mkdtemp('/tmp/radd-upload-proof-'))+'/fixture.whl';
  await writeFile(wheelFile,Buffer.from('PK browser transport fixture'));
  const {root}=await s.send('DOM.getDocument');
  const {nodeId}=await s.send('DOM.querySelector',{nodeId:root.nodeId,selector:'input[type=file]'});
  await s.send('DOM.setFileInputFiles',{nodeId,files:[wheelFile]});
  await s.click('button',t=>t.trim()==='Upload and install');
  await see('Install trusted plugin code?');
  await s.click('[role="dialog"] button',t=>t.trim()==='Upload and install');
  await see('Package installed. Find it below and enable it when ready.');
  assert.equal(uploaded.type,'application/octet-stream');
  assert.equal(uploaded.body.toString(),'PK browser transport fixture');
  await see('Inactive');
  await s.click('input[placeholder="Search by name or description…"]');
  await s.send('Input.insertText',{text:'absent-plugin'});
  await see('No plugins match your search.');
  await s.eval(`document.querySelector('input[placeholder="Search by name or description…"]').select()`);
  await s.send('Input.insertText',{text:'acme'});
  await see('Company extension');
  await s.click('button',t=>t.trim()==='Enable');
  await see('Applying plugin changes…');
  failDisable=true;
  await s.click('button',t=>t.trim()==='Cancel enable');
  await see('Required by dependent-plugin');
  assert(await s.eval(`document.querySelector('[role="alert"]').innerText.includes('Required by')`));
  failDisable=false;
  await s.click('button',t=>t.trim()==='Cancel enable');
  await see('Forget…');
  await s.click('button',t=>t.trim()==='Forget…');
  await see('Stored plugin data and the deployed package remain');
  assert(!await s.eval(`document.body.innerText.includes('migrations DOWN')`));
  await new Promise(resolve=>setTimeout(resolve,300));
  await s.screenshot(outputPath('radd-plugin-workflow-settings.png'));
  console.log('Plugin Settings proof passed: binary upload/install, search, activation pending, errors and retained data');
} finally {if(browser)await browser.close();await spa.close();}

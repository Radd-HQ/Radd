/** Built SPA proof: package management, pending restart and actionable failures. */
import assert from 'node:assert/strict';
import http from 'node:http';
import { readFileSync, existsSync, statSync } from 'node:fs';
import { mkdtemp, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { openBrowser } from './lib/cdp.mjs';
const dist = new URL('../dist/', import.meta.url).pathname;
const plugin = {id:'acme-tools',name:'acme-tools',version:'0.1.0',core:false,state:'installed',
  description:'Company extension',can_toggle:true,capabilities:[],active:false,restart_required:false,
  origin:'package',dependencies:[],problems:[]};
let failDisable = false;
let uploaded = null;
const server = http.createServer(async (req,res) => {
  const p = new URL(req.url, 'http://fixture').pathname;
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
    else if(p.endsWith('/plugins/acme-tools/enable')) {plugin.state='enabled';plugin.restart_required=true;data=[plugin];}
    else if(p.endsWith('/plugins/acme-tools/disable')) {
      if(failDisable) {res.writeHead(409,{'content-type':'application/json'});res.end(JSON.stringify({detail:'Required by dependent-plugin'}));return;}
      plugin.state='disabled';plugin.restart_required=false;data=[plugin];
    }
    else if(p.endsWith('/projects/summary')) data={total:0,related_count:0,permissions:[]};
    else if(p.endsWith('/page-spaces/summary')) data={total:0,permissions:[]};
    else if(p.includes('capabilities')) data={capabilities:[],nav:[],plugins:[],ui:[]};
    else if(p.includes('notifications')) data={items:[],notifications:[],unread_count:0,total:0};
    else if(p.includes('preferences')) data={};
    else if(p.endsWith('/instance')) data={work_week_days:['mon'],timelog_hours_per_day:8,timelog_days_per_week:5};
    res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify(data));return;
  }
  const file=path.join(dist,p);
  const target=existsSync(file)&&statSync(file).isFile()?file:path.join(dist,'index.html');
  res.setHeader('content-type',target.endsWith('.js')?'text/javascript':target.endsWith('.css')?'text/css':'text/html');
  res.end(readFileSync(target));
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
let browser;
try {
  browser=await openBrowser({port:18824,profile:await mkdtemp('/tmp/radd-plugin-proof-'),scale:1});
  const s=browser.session;
  await s.navigate(`http://127.0.0.1:${server.address().port}/settings/plugins`);
  const until=async text=>{
    for(let i=0;i<100;i++) {
      if(await s.eval(`document.body.innerText.includes(${JSON.stringify(text)})`))return;
      await new Promise(resolve=>setTimeout(resolve,50));
    }
    throw Error(`Missing ${text}: `+await s.eval('document.body.innerText'));
  };
  await until('Company extension');
  const wheelFile=(await mkdtemp('/tmp/radd-upload-proof-'))+'/fixture.whl';
  await writeFile(wheelFile,Buffer.from('PK browser transport fixture'));
  const {root}=await s.send('DOM.getDocument');
  const {nodeId}=await s.send('DOM.querySelector',{nodeId:root.nodeId,selector:'input[type=file]'});
  await s.send('DOM.setFileInputFiles',{nodeId,files:[wheelFile]});
  await s.click('button',t=>t.trim()==='Upload and install');
  await until('Install trusted plugin code?');
  await s.click('[role="dialog"] button',t=>t.trim()==='Upload and install');
  await until('Package installed. Find it below and enable it when ready.');
  assert.equal(uploaded.type,'application/octet-stream');
  assert.equal(uploaded.body.toString(),'PK browser transport fixture');
  await until('Not loaded on this server');
  await s.click('input[placeholder="Search by name or description…"]');
  await s.send('Input.insertText',{text:'absent-plugin'});
  await until('No plugins match your search.');
  await s.eval(`document.querySelector('input[placeholder="Search by name or description…"]').select()`);
  await s.send('Input.insertText',{text:'acme'});
  await until('Company extension');
  await s.click('button',t=>t.trim()==='Enable');
  await until('Restart required to apply this change');
  failDisable=true;
  await s.click('button',t=>t.trim()==='Disable');
  await until('Required by dependent-plugin');
  assert(await s.eval(`document.querySelector('[role="alert"]').innerText.includes('Required by')`));
  failDisable=false;
  await s.click('button',t=>t.trim()==='Disable');
  await until('Forget…');
  await s.click('button',t=>t.trim()==='Forget…');
  await until('Stored plugin data and the deployed package remain');
  assert(!await s.eval(`document.body.innerText.includes('migrations DOWN')`));
  await new Promise(resolve=>setTimeout(resolve,300));
  await s.send('Page.captureScreenshot',{format:'png'}).then(r=>import('node:fs').then(fs=>fs.writeFileSync('/tmp/radd-plugin-workflow/settings.png',Buffer.from(r.data,'base64'))));
  console.log('Plugin Settings proof passed: binary upload/install, search, activation pending, errors and retained data');
} finally {if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));}

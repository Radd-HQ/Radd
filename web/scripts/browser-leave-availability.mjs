/** RADD-1342: disabling Leave withdraws settings and cached status without reloading. */
import assert from 'node:assert/strict';
import http from 'node:http';
import {readFileSync, existsSync, statSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import path from 'node:path';
import {openBrowser} from './lib/cdp.mjs';

const dist = new URL('../dist/', import.meta.url).pathname;
let enabled = false;
let brokenRemote = false;
let brokenReads = 0;
let holdCurrent = false;
let releaseCurrent;
let abortedCurrent = 0;
const leaveReads = [];
const writes = [];
let saved = [];
const user = {id:'admin',name:'Admin',email:'admin@example.test',global_role:'admin',instance_role:'admin',permissions:['*'],timezone:'UTC'};
const period = {id:'absence',user_id:user.id,team_id:null,team_name:null,kind:'leave',label:'Fixture absence',start_date:'2026-09-21',end_date:'2026-09-27',created_by:user.id};
const server = http.createServer(async(req,res) => {
  const url = new URL(req.url,'http://fixture'), p = url.pathname;
  if (p === '/plugins/leave/missing.js') { brokenReads++; res.writeHead(404); res.end(); return; }
  if (p.startsWith('/api/')) {
    let data = [];
    if (p.endsWith('/auth/me')) data = user;
    else if (p.includes('capabilities')) data = {capabilities:[],nav:[],plugins:enabled?['leave']:[],remotes:enabled?[{name:'leave',remote_entry:brokenRemote?'/plugins/leave/missing.js':'/plugins/leave/remoteEntry.js',ui_api_version:'1.0.0'}]:[],widget_types:[],view_types:[]};
    else if (p === '/api/v1/leave' && req.method === 'POST') {
      let raw = ''; for await (const chunk of req) raw += chunk;
      data = { ...period, ...JSON.parse(raw), id: 'created' }; saved.push(data); writes.push(JSON.parse(raw));
    }
    else if (p === '/api/v1/leave/created' && req.method === 'DELETE') { saved = []; res.writeHead(204); res.end(); return; }
    else if (p.endsWith('/teams')) data = [{id:'team',name:'Test team'}];
    else if (p.startsWith('/api/v1/leave/')) {
      leaveReads.push(p);
      if (p.endsWith('/current') && holdCurrent) {
        res.on('close',()=>{ if (!res.writableEnded) abortedCurrent++; });
        await new Promise(resolve=>{ releaseCurrent=resolve; });
      }
      data = p.endsWith('/current') ? [{user_id:user.id,kind:'leave',label:period.label,until:period.end_date}] : p.endsWith('/holidays') ? saved.filter(x=>x.team_id) : [period,...saved.filter(x=>!x.team_id)];
    }
    else if (p.endsWith('/timesheet')) data = {start:'2026-09-21',end:'2026-09-27',total_seconds:3600,day_min_hours:6,day_max_hours:10,work_days:['mon','tue','wed','thu','fri'],entries:[{id:'work',worked_on:'2026-09-25',time_spent_seconds:3600,user,item:null,epic:null,project_key:null,category:null,note:'',external_source:''}]};
    else if (p.endsWith('/projects/summary') || p.endsWith('/page-spaces/summary')) data = {total:0,related_count:0,permissions:[]};
    else if (p.includes('notifications')) data = {items:[],notifications:[],unread_count:0,total:0};
    else if (p.includes('preferences')) data = {};
    else if (p.endsWith('/auth/totp')) data = {enabled:false,pending:false};
    else if (p.endsWith('/instance')) data = {work_week_days:['mon','tue','wed','thu','fri'],timelog_hours_per_day:8,timelog_days_per_week:5};
    res.writeHead(200,{'content-type':'application/json'});
    res.end(JSON.stringify(data));
    return;
  }
  const file = p.startsWith('/plugins/leave/') ? new URL('../../server/src/radd/modules/leave/ui/dist/'+p.slice('/plugins/leave/'.length),import.meta.url).pathname : path.join(dist,p), target = existsSync(file)&&statSync(file).isFile()?file:path.join(dist,'index.html');
  res.setHeader('content-type',target.endsWith('.js')?'text/javascript':target.endsWith('.css')?'text/css':'text/html');
  res.end(readFileSync(target));
});
await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
let browser;
try {
  browser = await openBrowser({port:18827,profile:await mkdtemp('/tmp/radd-leave-availability-'),scale:1});
  const s = browser.session, base = `http://127.0.0.1:${server.address().port}`;
  const until = async(predicate,label) => {
    for (let i=0;i<600;i++) {
      if (await predicate()) return;
      await new Promise(resolve => setTimeout(resolve,50));
    }
    throw Error(label+': '+await s.eval('document.body.innerText')+' '+JSON.stringify(s.consoleErrors));
  };
  const text = t => s.eval(`document.body.innerText.includes(${JSON.stringify(t)})`);
  const refresh = () => s.eval(`window.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:["capabilities"]})`);
  const heading = () => s.eval(`Array.from(document.querySelectorAll('h2')).some(h => h.textContent==='Leave')`);
  const away = () => s.eval(`document.querySelectorAll('[aria-label="On leave"]').length`);
  await s.navigate(base+'/settings/profile');
  await until(() => text('Display name'),'profile ready');
  assert.equal(await heading(),false);
  assert.equal(await away(),0);
  assert.deepEqual(leaveReads,[], 'disabled profile and avatars must not request Leave');
  // Same document throughout each transition: no reload or navigation can hide stale state.
  await s.eval('window.leaveProof = true');
  enabled = true;
  await until(async() => await heading() && await away()>0 && await text('Fixture absence'),'live enable');
  assert(leaveReads.includes('/api/v1/leave/mine'));
  await s.click('button', t=>t.trim()==='Add leave');
  await until(()=>writes.length===1,'personal leave saved');
  assert.equal(writes[0].team_id,undefined);
  assert.match(writes[0].start_date,/^\d{4}-\d{2}-\d{2}$/);
  await until(()=>s.eval(`document.querySelectorAll('section[aria-label="Leave"] li').length===2`),'new leave rendered');
  await s.eval(`document.querySelector('section[aria-label="Leave"] li:last-child button').click()`);
  await until(()=>s.eval(`document.querySelectorAll('section[aria-label="Leave"] li').length===1`),'leave removal works');
  enabled = false; await refresh();
  await until(async() => !await heading() && await away()===0,'live disable clears cached settings and badges');
  assert(await s.eval('window.leaveProof === true'));
  const beforeBroken = leaveReads.length;
  brokenRemote = true; enabled = true; await refresh();
  await until(()=>brokenReads>0,'failed bundle requested');
  assert.equal(await heading(),false);
  assert.equal(await away(),0);
  assert.equal(leaveReads.length,beforeBroken,'failed plugin must not leave host-owned queries running');
  brokenRemote = false; enabled = false; await refresh();
  await s.screenshot('/tmp/radd-leave-profile-disabled.png');
  enabled = true; await refresh();
  await until(() => heading(),'profile re-enable');
  await s.screenshot('/tmp/radd-leave-profile-enabled.png');
  await s.navigate(base+'/settings/timelogging');
  await until(() => text('Add holiday'),'plugin contributes holidays to Time logging');
  assert(await s.eval(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Add holiday').disabled`));
  await s.eval(`const select=document.querySelector('section[aria-label="Holidays"] select'); select.value='team'; select.dispatchEvent(new Event('change',{bubbles:true}));`);
  await s.click('button', t=>t.trim()==='Add holiday');
  await until(()=>writes.length===2,'holiday saved');
  assert.equal(writes[1].team_id,'team');
  enabled = false; await refresh();
  await until(async() => !await text('Add holiday'),'holiday contribution withdrawn live');
  enabled = true;
  await s.navigate(base+'/timesheet?g=person&d=2026-09-25');
  await until(() => s.eval(`document.querySelector('td[title="Leave: Fixture absence"]') !== null`),'timesheet leave loaded');
  enabled = false; await refresh();
  await until(() => s.eval(`document.querySelector('td[title="Leave: Fixture absence"]') === null && document.querySelectorAll('[aria-label="On leave"]').length === 0`),'timesheet cached leave removed');
  const before = leaveReads.length;
  await s.navigate(base+'/timesheet?g=person&d=2026-09-25');
  await until(() => text('Admin'),'disabled timesheet ready');
  assert.equal(leaveReads.length,before,'disabled timesheet must not request Leave');
  assert.equal(await away(),0);
  await s.navigate(base+'/settings/profile');
  await until(()=>text('Display name'),'profile for in-flight test');
  holdCurrent = true; enabled = true; await refresh();
  await until(()=>Boolean(releaseCurrent),'status request in flight');
  enabled = false; await refresh();
  await until(async()=>!await heading() && abortedCurrent>0,'disable aborts status request');
  releaseCurrent(); holdCurrent=false;
  assert.equal(await away(),0);
  enabled=true; await refresh();
  await until(async()=>await heading() && await away()>0,'fresh activation after aborted query');
  enabled=false; await refresh();
  await until(async()=>!await heading() && await away()===0,'final withdrawal');
  console.log(JSON.stringify({passed:true,checks:['disabled Profile hides Leave and makes no leave requests','live enable restores form and indicators','live disable removes section and cached indicators','failed bundle leaves no settings, badges or data requests','re-enable restores Profile','personal leave creation and removal work','Holidays slot mounts and unmounts live','holiday submission includes selected team','timesheet clears cached leave on disable','disabled timesheet makes no leave requests','in-flight status request aborts on disable','fresh activation after cancellation restores status'],leaveReads}));
} finally {
  releaseCurrent?.();
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}

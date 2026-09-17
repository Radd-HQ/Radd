/** RADD-1213: run with a local session cookie file; never prints credentials. */
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { openBrowser, sleep } from './lib/cdp.mjs';
const baseUrl = process.env.RADD_PROOF_BASE_URL || 'http://127.0.0.1:8000';
const cookieFile = process.env.RADD_PROOF_COOKIE_FILE;
if (!cookieFile) throw Error('Set RADD_PROOF_COOKIE_FILE to a file containing a local radd_session cookie.');
const output = process.env.RADD_PROOF_OUTPUT_DIR || '/tmp/radd-access-proof';
await mkdir(output, {recursive:true});
const {session,close}=await openBrowser({port:9498,profile:output+"/chrome-restriction",width:1440,height:1050});
const api=`const api=async(method,path,body)=>{const r=await fetch('/api/v1'+path,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});if(!r.ok)throw Error(path+': '+r.status);return r.status===204?null:r.json();};`;
let context;
try {
 await session.send('Network.setCookie',{name:'radd_session',value:(await readFile(cookieFile,'utf8')).trim(),url:baseUrl,httpOnly:true});
 await session.navigate(baseUrl,1200);
 context=await session.eval(`(async()=>{${api}
 const me=await api('GET','/auth/me');
 const space=await api('POST','/page-spaces',{name:'Access verification '+Date.now()});
 const page=await api('POST','/pages',{space_id:space.id,title:'Restriction lifecycle verification',body:'Temporary local verification page.'});
 const rows=await api('POST','/grants',{resource_type:'page',resource_id:page.id,subject_type:'user',subject_id:me.id,access:'read'});
 await api('DELETE','/grants/'+rows[0].id);
 return {space,page};})()`);
 await session.navigate(`${baseUrl}/pages/${context.space.slug}/${context.page.slug}`,1600);
 await session.click('button[aria-label="Restrict page"]');await sleep(500);
 const checks={};
 checks.restrictionRemainsVisible=await session.eval(`document.querySelector('[role=dialog]').innerText.includes('Restricted read')`);
 await session.screenshot(output+'/restriction-retained.png');
 await session.click('[role=dialog] button',t=>t.trim()==='Restore parent access…');
 checks.confirmationVisible=await session.eval(`document.querySelector('[role=dialog]').innerText.includes('Remove the allow list')`);
 await session.click('[role=dialog] button',t=>t.trim()==='Restore parent access');await sleep(600);
 checks.resetPersists=await session.eval(`(async()=>{${api}return (await api('GET','/grants/restrictions/page/${context.page.id}')).length===0;})()`);
 console.log(JSON.stringify(checks));
 if(Object.values(checks).some(v=>!v))throw Error('Restriction browser check failed');
 await writeFile(output+'/restriction-browser-checks.json',JSON.stringify(checks,null,2));
} finally {
 if(context)await session.eval(`(async()=>{${api}await api('DELETE','/page-spaces/${context.space.id}?force=true');})()`);
 await close();
}

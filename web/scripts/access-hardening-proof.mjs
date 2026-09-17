/** RADD-1213: run with a local session cookie file; never prints credentials. */
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { openBrowser, sleep } from './lib/cdp.mjs';
const baseUrl = process.env.RADD_PROOF_BASE_URL || 'http://127.0.0.1:8000';
const cookieFile = process.env.RADD_PROOF_COOKIE_FILE;
if (!cookieFile) throw Error('Set RADD_PROOF_COOKIE_FILE to a file containing a local radd_session cookie.');
const output = process.env.RADD_PROOF_OUTPUT_DIR || '/tmp/radd-access-proof';
await mkdir(output, {recursive:true});
const {session, close}=await openBrowser({port:9497, profile:output+"/chrome",width:1440,height:1050});
try {
 const cookie=(await readFile(cookieFile,'utf8')).trim();
 await session.send('Network.setCookie',{name:'radd_session',value:cookie,url:baseUrl,httpOnly:true});
 await session.navigate(baseUrl+'/settings/users',1800);
 await session.click("button[aria-label^='Roles held by']",()=>true);
 await sleep(500);
 await session.click('button',t=>t.trim()==='Grant role');
 await sleep(500);
 const checks={};
 checks.dialogOpened=await session.eval('!!document.querySelector("[role=dialog]")');
 checks.defaultScopeUnchecked=await session.eval('!document.querySelector("[role=dialog] input[type=checkbox]").checked');
 checks.submitDisabled=await session.eval('document.querySelector("[role=dialog] button[type=submit]").disabled');
 checks.expiryVisible=await session.eval('!!document.querySelector("[role=dialog] input[type=datetime-local]")');
 await session.screenshot(output+'/grant-explicit-scope.png');
 await session.click('[role=dialog] button',t=>t.trim()==='Viewer');
 checks.roleAloneStillDisabled=await session.eval('document.querySelector("[role=dialog] button[type=submit]").disabled');
 await session.click('[role=dialog] input[type=checkbox]',()=>true);
 checks.explicitGlobalEnables=await session.eval('!document.querySelector("[role=dialog] button[type=submit]").disabled');
 await session.screenshot(output+'/grant-global-warning.png');
 console.log(JSON.stringify(checks));
 if(Object.values(checks).some(x=>!x))throw Error('Browser check failed');
 await writeFile(output+'/browser-checks.json',JSON.stringify(checks,null,2));
} finally {await close();}

/** Regression: draft preview, honest save status, and relevant integration policies. */
import assert from "node:assert/strict";
import http from "node:http";
import { execFileSync } from "node:child_process";
import { readFileSync, existsSync, statSync } from "node:fs";
import { mkdtemp } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { openBrowser } from "./lib/cdp.mjs";
import { CORE_PLUGINS } from "./lib/core-plugins.mjs";

const dist = fileURLToPath(new URL("../dist/", import.meta.url));
const root = fileURLToPath(new URL("../../", import.meta.url));
const fixture = JSON.parse(execFileSync(path.join(root, "server/.venv/bin/python"), ["-c", `
import asyncio, importlib, json
from radd.config import settings
from radd.kernel import load_plugins
load_plugins(settings.modules)
router = importlib.import_module("radd.modules.automations.router")
async def allowed(*args, **kwargs): return True
router.authz.holds = allowed
router.authz.require = allowed
async def main():
    catalog = await router.get_catalog(None, None)
    templates = await router.list_templates(None, None)
    print(json.dumps({"catalog": catalog.model_dump(mode="json"), "templates": [t.model_dump(mode="json") for t in templates]}))
asyncio.run(main())
`], {cwd: root, encoding: "utf8"}));
let testRequest = null;
let saved = { id: "existing", name: "Existing completion policy", enabled: false, version: 1, orientation: "vertical",
  triggers: [{node_id:"t",event_type:"item.updated"}],
  nodes: [{id:"t",kind:"trigger",type:"trigger.event",params:{event:"item.updated"}},
          {id:"c",kind:"action",type:"action.add_comment",params:{body:"Saved comment",visibility:"public"}}],
  edges: [{source:"t",port:"out",target:"c"}] };
let connection = {id:"host",name:"Review host",base_url:"https://github.test",active:true,verify_ssl:true,has_token:true,has_secret:true,repo_count:1};
let repository = {id:"repo",connection_id:"host",full_name:"team/repo",project_id:null,enabled:true,link_all_projects:true,mirror_time:false};
const connectionPatches = [];
const repoPatches = [];
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  if (url.pathname.startsWith("/api/")) {
    let data = [];
    if (url.pathname.endsWith("/auth/me")) data = {id:"review",name:"Reviewer",email:"review@example.test",instance_role:"admin",permissions:["global.manage","automation.manage"],timezone:"UTC"};
    else if (url.pathname.endsWith("/automations/catalog")) data = fixture.catalog;
    else if (url.pathname.endsWith("/automations/templates")) data = fixture.templates;
    else if (url.pathname.endsWith("/automations")) data = [saved];
    else if (url.pathname.endsWith("/automations/existing") && req.method === "PATCH") {
      let body=""; for await (const chunk of req) body += chunk;
      saved={...saved,...JSON.parse(body),version:saved.version+1}; data=saved;
    }
    else if (url.pathname.endsWith("/automations/existing/test")) {
      let body=""; for await (const chunk of req) body += chunk;
      testRequest=JSON.parse(body);
      data={rule_id:saved.id,item_id:null,matched:true,trigger_node_id:"t",nodes:[],dropped:[],findings:[],
        would_apply:[{node_id:"c",type:"action.add_comment",params:testRequest.nodes[1].params,resolves:true,refused:false,item_key:"",resolved:{},detail:testRequest.nodes[1].params.body}]};
    }
    else if (url.pathname.endsWith("/github/connections")) data = [connection];
    else if (url.pathname.endsWith("/github/repos")) data = [repository];
    else if (url.pathname.endsWith("/github/connections/host") && req.method === "PATCH") {
      let body=""; for await(const chunk of req) body+=chunk;
      const patch=JSON.parse(body); connectionPatches.push(patch); connection={...connection,...patch}; data=connection;
    }
    else if (url.pathname.endsWith("/github/repos/repo") && req.method === "PATCH") {
      let body=""; for await(const chunk of req) body+=chunk;
      const patch=JSON.parse(body); repoPatches.push(patch); repository={...repository,...patch}; data=repository;
    }
    else if (url.pathname.endsWith("/github/repos/repo/backfill")) data={linked:2,branches:1,commits:1,pull_requests:1,unknown_keys:["MISSING-99"],worklogs:{pending:3,unmatched_authors:["unmapped-person"]},errors:["Could not read historical comments"]};
    else if (url.pathname.endsWith("/github/connections/host/test")) {
      res.writeHead(409,{"content-type":"application/json"});res.end(JSON.stringify({detail:"Host credentials rejected"}));return;
    }
    else if (url.pathname.includes("/samples/events")) data = {sampled:0,subjects:[],declared_schema:{},paths:[],declared_paths:[],changed_fields:[]};
    else if (url.pathname.endsWith("/projects/summary") || url.pathname.endsWith("/page-spaces/summary")) data = {total:0,permissions:[],related_count:0};
    else if (url.pathname.endsWith("/preferences")) data = {};
    else if (url.pathname.includes("capabilities")) data = {capabilities:[],nav:[],plugins:[...CORE_PLUGINS,"github"],ui:[]};
    else if (url.pathname.includes("/notifications")) data = {items:[],notifications:[],unread_count:0,total:0};
    else if (url.pathname.endsWith("/ai/status")) data = {enabled:false,features:{}};
    else if (url.pathname.endsWith("/instance")) data = {work_week_days:["mon"],timelog_hours_per_day:8,timelog_days_per_week:5};
    res.writeHead(200, {"content-type":"application/json"}); res.end(JSON.stringify(data)); return;
  }
  let file = path.resolve(dist, "." + url.pathname);
  if (!file.startsWith(dist) || !existsSync(file) || statSync(file).isDirectory()) file = path.join(dist, "index.html");
  const mime = {".js":"text/javascript", ".css":"text/css", ".svg":"image/svg+xml", ".html":"text/html"}[path.extname(file)] ?? "application/octet-stream";
  res.writeHead(200,{"content-type":mime}); res.end(readFileSync(file));
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;
let browser;
try {
  browser = await openBrowser({port:18787,profile:await mkdtemp("/tmp/radd-review-browser-"),scale:1});
  const s = browser.session;
  const wait = async (expression) => {
    for(let i=0;i<100;i++) { if(await s.eval(expression)) return; await new Promise(r=>setTimeout(r,50)); }
    throw new Error("Not found: " + expression + "\n" + await s.eval("document.body.innerText"));
  };
  const click = async (text) => s.eval(`(()=>{const button=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===${JSON.stringify(text)});button?.click();return !!button;})()`);
  await s.navigate(base+"/settings/email");
  await wait(`document.querySelector('[data-integration-automations="Email"]')?.innerText.includes('No relevant automation policies')`);
  assert(!await s.eval(`document.querySelector('[data-integration-automations="Email"]').innerText.includes('Existing completion policy')`));
  await s.navigate(base+"/settings/automations");
  await wait(`!!document.querySelector('[aria-label="Edit Existing completion policy"]')`);
  await s.eval(`document.querySelector('[aria-label="Edit Existing completion policy"]').click()`);
  await wait(`!!document.querySelector('.react-flow__node[data-id="c"]')`);
  await s.eval(`document.querySelector('.react-flow__node[data-id="c"]').click()`);
  await wait(`[...document.querySelectorAll('input,textarea')].some(i=>i.value==='Saved comment')`);
  assert(await click("Save changes"));
  await wait(`!![...document.querySelectorAll('span')].find(s=>s.textContent.trim()==='Saved') && ![...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='Saving…')`);
  await s.eval(`(()=>{const input=[...document.querySelectorAll('input,textarea')].find(i=>i.value==='Saved comment'); const prototype=input.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(prototype,'value').set.call(input,'Unsaved comment');input.dispatchEvent(new Event('input',{bubbles:true}));return true;})()`);
  await new Promise(r=>setTimeout(r,300));
  assert(await s.eval(`[...document.querySelectorAll('input,textarea')].some(i=>i.value==='Unsaved comment')`));
  assert(await s.eval(`document.body.innerText.includes('Unsaved changes')`));
  assert(!await s.eval(`[...document.querySelectorAll('span')].some(s=>s.textContent.trim()==='Saved')`), "Editing clears Saved");
  assert(await click("Run"));
  await wait(`document.querySelector('[data-run-result]')?.innerText.includes('Unsaved comment')`);
  assert.equal(testRequest.nodes[1].params.body, "Unsaved comment");
  assert.deepEqual(testRequest.edges, saved.edges);
  assert.equal(saved.nodes[1].params.body,"Saved comment");
  await s.navigate(base+"/settings/vcs?host=github");
  await wait(`document.body.innerText.includes('Review host')`);
  assert(await click("Edit"));
  await wait(`[...document.querySelectorAll('input')].some(i=>i.value==='Review host')`);
  await s.eval(`(()=>{const input=[...document.querySelectorAll('input')].find(i=>i.value==='Review host');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'Renamed host');input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  assert(await click("Save host"));
  await wait(`document.body.innerText.includes('Renamed host') && !document.body.innerText.includes('Save host')`);
  assert.equal(connectionPatches[0].name,"Renamed host");
  assert(!("webhook_secret" in connectionPatches[0]) && !("api_token" in connectionPatches[0]), "Blank credentials are preserved");
  assert(await click("Pause"));
  await wait(`document.body.innerText.includes('Resume')`);
  assert.equal(connection.active,false);
  assert(await click("Resume"));
  await wait(`document.body.innerText.includes('Pause')`);
  assert(await click("Backfill"));
  await wait(`document.body.innerText.includes('MISSING-99') && document.body.innerText.includes('unmapped-person') && document.body.innerText.includes('Could not read historical comments')`);
  await s.eval(`(()=>{const label=[...document.querySelectorAll('label')].find(l=>l.textContent.trim()==='Ingest webhooks');label.querySelector('input').click();})()`);
  await wait(`!![...document.querySelectorAll('label')].find(l=>l.textContent.trim()==='Ingest webhooks' && !l.querySelector('input').checked)`);
  assert.equal(repoPatches.at(-1).enabled,false);
  assert(await click("Test"));
  await wait(`document.body.innerText.includes('Host credentials rejected')`);
  console.log("Verified: unrelated rules absent from Email; edits clear Saved; dry run previews the unsaved graph without saving it; host editing/pause, repository controls, backfill diagnostics, and errors work.");

} finally {
  browser?.close();
  await new Promise(resolve=>server.close(resolve));
}

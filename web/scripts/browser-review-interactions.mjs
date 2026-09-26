/** Review regression browser check, using the current catalog and mocked integration APIs. */
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
const mail = fixture.templates.find(t => t.key === "mailintake.tell_requester_when_resolved");
let shapeRequests = 0;
const dynamic = {key:"review.dynamic", name:"Review dynamic shapes", group:"Email", description:"Review fixture", nodes:[
  {id:"t",kind:"trigger",type:"trigger.event",params:{event:"manual"}},
  {id:"c",name:"classify",kind:"gate",type:"ai.classify",params:{prompt:"Initial question",answers:["one","two"]}}
], edges:[{source:"t",port:"out",target:"c"}]};
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  if (url.pathname.startsWith("/api/")) {
    let data = [];
    if (url.pathname.endsWith("/auth/me")) data = {id:"review",name:"Reviewer",email:"review@example.test",instance_role:"admin",permissions:["global.manage","automation.manage"],timezone:"UTC"};
    else if (url.pathname.endsWith("/automations/catalog")) data = fixture.catalog;
    else if (url.pathname.endsWith("/automations/templates")) data = [...fixture.templates, dynamic];
    else if (url.pathname.endsWith("/automations")) data = [{id:"existing",name:"Existing completion policy",enabled:true,nodes:mail.nodes,edges:mail.edges}];
    else if (url.pathname.includes("/nodes/ai.classify/shape")) { shapeRequests++; data = {ports:["one","two","unavailable"],outputs:[{name:"answer",label:"Answer",kind:"enum",choices:["one","two"]}]}; }
    else if (url.pathname.includes("/samples/events")) data = {sampled:0,subjects:[],declared_schema:{},paths:[],declared_paths:[],changed_fields:[]};
    else if (url.pathname.endsWith("/projects/summary") || url.pathname.endsWith("/page-spaces/summary")) data = {total:0,permissions:[],related_count:0};
    else if (url.pathname.endsWith("/preferences")) data = {};
    else if (url.pathname.includes("capabilities")) data = {capabilities:[],nav:[],plugins:[...CORE_PLUGINS],ui:[]};
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
  await wait(`document.querySelector('[data-integration-automations="Email"]')?.innerText.includes('Existing completion policy')`);
  assert(await click("Tell the requester when resolved"));
  await wait(`document.querySelector('[role="dialog"]')?.innerText.includes('Notify contacts of resolution')`);
  assert(await s.eval(`(()=>{const label=[...document.querySelectorAll('[role="dialog"] label')].find(l=>l.textContent.trim()==='Enabled');return label && !label.querySelector('input').checked;})()`));
  await s.navigate(base+"/settings/email");
  await wait(`document.body.innerText.includes('Review dynamic shapes')`);
  assert(await click("Review dynamic shapes"));
  await wait(`!!document.querySelector('.react-flow__node[data-id="c"]')`);
  await s.eval(`document.querySelector('.react-flow__node[data-id="c"]').click()`);
  await wait(`[...document.querySelectorAll('input,textarea')].some(i=>i.value==='Initial question')`);
  await new Promise(r=>setTimeout(r,500));
  const before=shapeRequests;
  assert(before>0);
  assert(await s.eval(`(()=>{const input=[...document.querySelectorAll('input,textarea')].find(i=>i.value==='Initial question'); const prototype=input.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(prototype,'value').set.call(input,'Changed question');input.dispatchEvent(new Event('input',{bubbles:true}));return true;})()`));
  await new Promise(r=>setTimeout(r,700));
  assert.equal(shapeRequests,before,"prompt edits must not request a different node shape");
  console.log("Integration rules visible; templates open disabled; editing an AI prompt does not refetch its shape.");
} finally {
  browser?.close();
  await new Promise(resolve=>server.close(resolve));
}

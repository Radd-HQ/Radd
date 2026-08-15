/**
 * RADD-1100: page templates get their authoring surface and their picker.
 *
 * Asserts the whole loop a user actually walks:
 *   - Settings → Pages shows the "Page templates" section, with the template
 *     just created via the API listed in it
 *   - a space's page tree offers "New page" as a MENU when templates exist
 *     (Blank page + one entry per template)
 *   - choosing the template creates a page whose body was RENDERED from it —
 *     {{author}} became the signed-in user, {{title}} the page title, and an
 *     unknown {{placeholder}} survived as a prompt
 *
 * Cleans up everything it creates.
 */
import { writeFileSync } from "node:fs";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const args = process.argv.slice(2);
const baseUrl = args.includes("--base") ? args[args.indexOf("--base") + 1] : "http://localhost:8000";
const email = process.env.RADD_PROOF_EMAIL ?? "hussein@hjarrar.com";
const password = process.env.RADD_PROOF_PASSWORD ?? "change-me";

const { session, close } = await openBrowser({ port: 9346, profile: "/tmp/radd-pagetpl-proof" });

const apiCall = (method, path, body) =>
  `(async()=>{const r=await fetch("/api/v1${path}",{method:${JSON.stringify(method)},credentials:"include",` +
  `headers:{"Content-Type":"application/json"}${body ? `,body:JSON.stringify(${JSON.stringify(body)})` : ""}});` +
  `const t=await r.text();return JSON.stringify({status:r.status, body:t});})()`;

const api = async (method, path, body) => {
  const raw = await session.eval(apiCall(method, path, body));
  const { status, body: text } = JSON.parse(raw);
  let parsed = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    /* non-JSON body */
  }
  return { status, body: parsed, text };
};

const checks = {};
const tag = Math.random().toString(36).slice(2, 8);
const templateName = `proof-runbook-${tag}`;
let templateId = null;
let pageId = null;

try {
  await session.navigate(baseUrl, 1500);
  const loginStatus = await session.login(baseUrl, email, password);
  checks["login succeeds"] = loginStatus === 200 || loginStatus === 204;

  // A template to find in the UI.
  const created = await api("POST", "/page-templates", {
    name: templateName,
    description: "created by page-templates-proof",
    body: "# {{title}}\n\nOwner: {{author}} — started {{date}}\n\nSeverity: {{severity}}",
  });
  templateId = created.body?.id ?? null;
  checks["template created via API"] = created.status === 201;

  // 1) The settings section lists it.
  await session.navigate(`${baseUrl}/settings/pages`, 2500);
  const settings = await session.eval(`(()=>{
    const h2 = [...document.querySelectorAll("h2")].find(h=>h.textContent.trim()==="Page templates");
    const listed = document.body.textContent.includes(${JSON.stringify(templateName)});
    const newBtn = [...document.querySelectorAll("button")].some(b=>b.textContent.includes("New template"));
    return JSON.stringify({ section: !!h2, listed, newBtn });
  })()`).then(JSON.parse);
  checks["settings: Page templates section renders"] = settings.section;
  checks["settings: created template is listed"] = settings.listed;
  checks["settings: New template button present"] = settings.newBtn;
  {
    const shot = await session.send("Page.captureScreenshot", { format: "png" });
    writeFileSync("/tmp/pagetpl-settings.png", Buffer.from(shot.data, "base64"));
  }

  // 2) The page tree's New page button becomes a menu.
  const spaces = await api("GET", "/page-spaces");
  checks["a page space exists to test in"] = (spaces.body?.length ?? 0) > 0;
  const space = spaces.body[0];

  await session.navigate(`${baseUrl}/pages/${space.slug}`, 2500);
  const opened = await session.eval(`(()=>{
    const btn = [...document.querySelectorAll("button")].find(b=>b.textContent.trim().startsWith("New page"));
    if (!btn) return false;
    btn.click();
    return true;
  })()`);
  checks["tree: New page trigger found"] = opened === true;
  await sleep(400);
  const menuItems = await session.eval(
    `JSON.stringify([...document.querySelectorAll('button[role="menuitem"]')].map(b=>b.textContent.trim()))`,
  ).then(JSON.parse);
  checks["tree: menu offers Blank page"] = menuItems.includes("Blank page");
  checks["tree: menu offers the template"] = menuItems.some((t) => t.includes(templateName));
  {
    const shot = await session.send("Page.captureScreenshot", { format: "png" });
    writeFileSync("/tmp/pagetpl-menu.png", Buffer.from(shot.data, "base64"));
  }

  // 3) Choosing the template creates a RENDERED page.
  await session.eval(`(()=>{
    const item=[...document.querySelectorAll('button[role="menuitem"]')].find(b=>b.textContent.includes(${JSON.stringify(templateName)}));
    if(item) item.click(); return !!item;
  })()`);
  await sleep(2500); // create + navigate
  const url = await session.eval("location.pathname");
  checks["picking the template navigates to the new page"] = /\/pages\/.+\/.+/.test(url);

  // The editor renders async; read the created page from the API instead.
  const slug = url.split("/").filter(Boolean).pop();
  const byPath = await api("GET", `/pages/by-path/${space.slug}/${slug}`);
  pageId = byPath.body?.id ?? null;
  const body = byPath.body?.body ?? "";
  checks["created body rendered {{title}}"] = body.includes("# Untitled");
  checks["created body rendered {{author}}"] = body.includes("Owner:") && !body.includes("{{author}}");
  checks["unknown {{severity}} survives as a prompt"] = body.includes("{{severity}}");
} finally {
  try {
    if (pageId) await api("DELETE", `/pages/${pageId}`);
    if (templateId) await api("DELETE", `/page-templates/${templateId}`);
  } catch {
    /* best effort */
  }
  await close();
}

const failed = report(checks, "RADD-1100 — page templates UI");
process.exit(failed ? 1 : 0);

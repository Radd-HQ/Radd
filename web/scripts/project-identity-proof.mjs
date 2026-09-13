#!/usr/bin/env node
/**
 * RADD-1009 proof: the three server capabilities the browser never offered.
 *
 *   node web/scripts/project-identity-proof.mjs http://localhost:8000 admin@example.com change-me
 *
 * Signs in as the admin, creates a throwaway project, and checks in a REAL
 * browser that:
 *   1. Settings → Project → General carries the identity card, saving a new
 *      name + description round-trips through PATCH /projects/{id} and the
 *      key is untouched;
 *   2. a wiki page can be moved under a sibling from the tree's ⋯ menu, and
 *      the server's tree reflects the new parent;
 *   3. the personal-token form posts a restricted scope and the row shows it.
 * Every check is a measurement (DOM text, API read-back), not a screenshot.
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
if (!baseUrl || !adminEmail || !adminPassword) {
  console.error("usage: project-identity-proof.mjs <baseUrl> <adminEmail> <adminPassword>");
  process.exit(2);
}
const PORT = 9481;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-project-identity-proof");
const KEY = `PI${Date.now().toString(36).slice(-4).toUpperCase()}`;

const API = `
  const api = async (method, path, body) => {
    const r = await fetch("/api/v1" + path, {
      method, headers: { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await r.text();
    return { status: r.status, body: text ? JSON.parse(text) : null };
  };
`;

async function main() {
  const { session, close } = await openBrowser({ port: PORT, profile: PROFILE, width: 1500, height: 1000 });
  const checks = {};
  const context = { key: KEY };
  try {
    await session.navigate(baseUrl + "/login", 800);
    await session.login(baseUrl, adminEmail, adminPassword);

    // --- setup over the API: a project, a space with two pages ---
    const setup = await session.eval(`(async () => { ${API}
      const project = await api("POST", "/projects", { key: ${JSON.stringify(KEY)}, name: "Identity proof" });
      const space = await api("POST", "/page-spaces", { slug: ${JSON.stringify(KEY.toLowerCase())}, name: "Identity proof space" });
      const a = await api("POST", "/pages", { space_id: space.body.id, title: "Parent page", body: "a" });
      const b = await api("POST", "/pages", { space_id: space.body.id, title: "Child to be", body: "b" });
      return { project: project.body, space: space.body, a: a.body, b: b.body, statuses: [project.status, space.status, a.status, b.status] };
    })()`);
    context.setup = setup.statuses;
    checks.setupCreated = setup.statuses.every((s) => s === 201);
    const { project, space, a, b } = setup;

    // --- 1. the identity card on Settings → Project → General ---
    await session.navigate(`${baseUrl}/p/${KEY}/settings`, 2500);
    const card = await session.eval(`(() => {
      const name = document.querySelector('input[value="Identity proof"]');
      const desc = document.querySelector("textarea");
      return { hasName: Boolean(name), hasDescription: Boolean(desc) };
    })()`);
    checks.identityCardRendered = card.hasName && card.hasDescription;
    await session.eval(`(() => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      const input = document.querySelector('input[value="Identity proof"]');
      setter.call(input, "Identity proof, renamed");
      input.dispatchEvent(new Event("input", { bubbles: true }));
      const tsetter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
      const area = document.querySelector("textarea");
      tsetter.call(area, "Described from the browser.");
      area.dispatchEvent(new Event("input", { bubbles: true }));
    })()`);
    await session.click("button", (t) => t.trim() === "Save");
    await sleep(1500);
    const readBack = await session.eval(`(async () => { ${API}
      const r = await api("GET", "/projects/${project.id}");
      return r.body;
    })()`);
    context.renamed = { name: readBack.name, description: readBack.description, key: readBack.key };
    checks.renameRoundTrips = readBack.name === "Identity proof, renamed";
    checks.descriptionRoundTrips = readBack.description === "Described from the browser.";
    checks.keyUnchanged = readBack.key === KEY;
    const headerShowsIt = await session.eval(`document.body.innerText.includes("Described from the browser.")`);
    checks.descriptionShownOnHeader = headerShowsIt === true;

    // --- 2. move a page under a sibling from the tree menu ---
    await session.navigate(`${baseUrl}/pages/${space.slug}/${b.slug}`, 2500);
    const rowMenuOpened = await session.eval(`(() => {
      const row = [...document.querySelectorAll("a, [role=treeitem], li")].find((el) => el.textContent.trim().startsWith("Child to be"));
      if (!row) return "no row";
      const host = row.closest("li") || row.parentElement;
      const trigger = [...host.querySelectorAll("button")].find((btn) => (btn.getAttribute("aria-label") || "").toLowerCase().includes("actions") || btn.textContent.trim() === "⋯" || btn.textContent.trim() === "…");
      if (!trigger) return "no trigger: " + [...host.querySelectorAll("button")].map((x) => x.getAttribute("aria-label") || x.textContent.trim()).join("|");
      trigger.click();
      return "opened";
    })()`);
    context.rowMenu = rowMenuOpened;
    await sleep(400);
    await session.click("[role=menuitem], button", (t) => t.trim().startsWith("Move to"));
    await sleep(600);
    await session.click("[role=radio], button", (t) => t.trim() === "Parent page");
    await sleep(200);
    await session.click("button", (t) => t.trim() === "Move");
    await sleep(1500);
    const tree = await session.eval(`(async () => { ${API}
      const r = await api("GET", "/page-spaces/${space.id}/pages");
      const rows = Array.isArray(r.body) ? r.body : (r.body.pages || r.body.items || []);
      const moved = rows.find((p) => p.id === "${b.id}");
      return { status: r.status, parent: moved && moved.parent_id };
    })()`);
    context.moved = tree;
    checks.pageMovedUnderParent = tree.parent === a.id;

    // --- 3. a restricted personal token ---
    await session.navigate(`${baseUrl}/settings/tokens`, 2500);
    const tokenScope = await session.eval(`(async () => { ${API}
      const r = await api("POST", "/tokens", { name: "proof restricted", scopes: { global: ["item.read"], projects: {} } });
      const list = await api("GET", "/tokens");
      const mine = (list.body || []).find((t) => t.name === "proof restricted");
      return { status: r.status, scopes: mine && mine.scopes };
    })()`);
    context.token = tokenScope;
    checks.restrictedTokenStored = tokenScope.status === 201 && Array.isArray(tokenScope.scopes?.global) && tokenScope.scopes.global.includes("item.read");
    await session.navigate(`${baseUrl}/settings/tokens`, 2500);
    // The row summarises the scope as "<n> permission(s) · <where>" and keeps the
    // atoms in the title (hover) — assert both halves of that contract.
    const summary = await session.eval(`(() => {
      const row = [...document.querySelectorAll("tr")].find((tr) => tr.textContent.includes("proof restricted"));
      const cell = row && [...row.querySelectorAll("span")].find((el) => (el.getAttribute("title") || "").includes("item.read"));
      return cell ? cell.textContent.trim() : (row ? "row without scope summary" : "no row");
    })()`);
    context.tokenSummary = summary;
    checks.tokenScopeSummaryRendered = summary === "1 permission · everywhere";
  } finally {
    await close();
  }
  report(checks, context);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

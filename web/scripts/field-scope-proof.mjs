#!/usr/bin/env node
/**
 * RADD-1158 proof: the New Item form offers only the custom fields IN SCOPE
 * for the project it creates in.
 *
 *   node web/scripts/field-scope-proof.mjs http://localhost:8000 admin@example.com change-me
 *
 * Signs in as an admin, creates two throwaway projects (A and B), one GLOBAL
 * custom field and one scoped to A only, then checks in a REAL browser that:
 *   1. GET /fields?project_id=B carries the global field and not A's;
 *   2. the New Item modal opened from project A lists BOTH fields;
 *   3. the New Item modal opened from project B lists the global one ONLY —
 *      the field scoped to A never renders there.
 * Every check reads the DOM (label text inside the dialog) or the API.
 * The fields and both projects are deleted at the end.
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
if (!baseUrl || !adminEmail || !adminPassword) {
  console.error("usage: field-scope-proof.mjs <baseUrl> <adminEmail> <adminPassword>");
  process.exit(2);
}
const PORT = 9487;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-field-scope-proof");
const STAMP = Date.now().toString(36).slice(-4).toUpperCase();
const KEY_A = `FA${STAMP}`;
const KEY_B = `FB${STAMP}`;
const GLOBAL_NAME = `Global field ${STAMP}`;
const SCOPED_NAME = `Only in A ${STAMP}`;

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

/** Label text of every control inside the open dialog's "Custom fields" group. */
const DIALOG_FIELD_LABELS = `(() => {
  const dialog = document.querySelector('[role="dialog"]');
  if (!dialog) return null;
  const group = [...dialog.querySelectorAll("fieldset")]
    .find((f) => (f.querySelector("legend")?.textContent || "").trim() === "Custom fields");
  if (!group) return [];
  return [...group.querySelectorAll("label")].map((l) => (l.textContent || "").trim());
})()`;

async function openNewItem(session, key) {
  await session.navigate(`${baseUrl}/p/${key}`, 2500);
  await session.click("button", (t) => t.trim() === "New item");
  await sleep(1200);
  return session.eval(DIALOG_FIELD_LABELS);
}

async function main() {
  const { session, close } = await openBrowser({ port: PORT, profile: PROFILE, width: 1500, height: 1000 });
  const checks = {};
  const context = { keyA: KEY_A, keyB: KEY_B };
  let ids = null;
  try {
    await session.navigate(baseUrl + "/login", 800);
    const login = await session.login(baseUrl, adminEmail, adminPassword);
    checks.loggedIn = login === 200 || login === 204;

    const setup = await session.eval(`(async () => { ${API}
      const a = await api("POST", "/projects", { key: ${JSON.stringify(KEY_A)}, name: "Field scope A" });
      const b = await api("POST", "/projects", { key: ${JSON.stringify(KEY_B)}, name: "Field scope B" });
      const global = await api("POST", "/fields", { key: "g_" + ${JSON.stringify(STAMP.toLowerCase())}, name: ${JSON.stringify(GLOBAL_NAME)}, type: "text", project_ids: [] });
      const scoped = await api("POST", "/fields", { key: "a_" + ${JSON.stringify(STAMP.toLowerCase())}, name: ${JSON.stringify(SCOPED_NAME)}, type: "text", project_ids: [a.body.id] });
      return { a: a.body, b: b.body, global: global.body, scoped: scoped.body,
        statuses: [a.status, b.status, global.status, scoped.status] };
    })()`);
    context.setup = setup.statuses;
    checks.setupCreated = setup.statuses.every((s) => s === 201 || s === 200);
    ids = setup;

    // 1. The API narrows by project.
    const listed = await session.eval(`(async () => { ${API}
      const inA = await api("GET", "/fields?project_id=" + ${JSON.stringify(setup.a.id)});
      const inB = await api("GET", "/fields?project_id=" + ${JSON.stringify(setup.b.id)});
      return { inA: inA.body.map((f) => f.name), inB: inB.body.map((f) => f.name) };
    })()`);
    checks.apiScopedListHasBothInA = listed.inA.includes(GLOBAL_NAME) && listed.inA.includes(SCOPED_NAME);
    checks.apiScopedListExcludesAFieldInB = listed.inB.includes(GLOBAL_NAME) && !listed.inB.includes(SCOPED_NAME);

    // 2. The modal in project A offers both.
    const labelsA = await openNewItem(session, KEY_A);
    context.labelsA = labelsA;
    checks.modalOpenedInA = Array.isArray(labelsA);
    checks.modalInAListsGlobalAndScoped =
      Array.isArray(labelsA) && labelsA.includes(GLOBAL_NAME) && labelsA.includes(SCOPED_NAME);

    // 3. The modal in project B offers the global field only.
    const labelsB = await openNewItem(session, KEY_B);
    context.labelsB = labelsB;
    checks.modalOpenedInB = Array.isArray(labelsB);
    checks.modalInBListsGlobalOnly =
      Array.isArray(labelsB) && labelsB.includes(GLOBAL_NAME) && !labelsB.includes(SCOPED_NAME);
  } finally {
    if (ids) {
      const cleanup = await session.eval(`(async () => { ${API}
        const out = [];
        for (const path of [
          "/fields/" + ${JSON.stringify(ids.scoped?.id)}, "/fields/" + ${JSON.stringify(ids.global?.id)},
          "/projects/" + ${JSON.stringify(ids.a?.id)}, "/projects/" + ${JSON.stringify(ids.b?.id)},
        ]) out.push((await api("DELETE", path)).status);
        return out;
      })()`).catch((e) => String(e));
      context.cleanup = cleanup;
    }
    await close();
  }
  report(checks, context);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});

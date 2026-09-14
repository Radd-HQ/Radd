/**
 * Browser proof for the audit ledger page (spec 123, RADD-1170).
 *
 * A clean tsc + vite build cannot tell whether the page says anything an
 * auditor can use, so this drives Chrome over CDP against a running Radd:
 *
 *   1. signs in, renames a label through the API (a `label.updated` with a
 *      real old → new diff);
 *   2. opens Settings → Audit log filtered to that label by URL
 *      (`?entity=label&q=…`) and asserts the row reads "Label updated",
 *      links to Settings → Labels, and shows "Name: old → new";
 *   3. filters by changed field (`?field=name`) and asserts every row's diff
 *      mentions Name;
 *   4. filters to items and asserts an entity link points at an issue;
 *   5. takes a screenshot for the record.
 *
 * Usage: node scripts/audit-proof.mjs <baseUrl> [email] [password]
 *   (defaults: RADD_PROOF_EMAIL / RADD_PROOF_PASSWORD, else admin@example.com / change-me)
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl = "http://localhost:8000", emailArg, passwordArg] = process.argv.slice(2);
const email = emailArg ?? process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = passwordArg ?? process.env.RADD_PROOF_PASSWORD ?? "change-me";
const PORT = 9471;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-audit-proof-profile");
const tag = `audit-proof-${Date.now().toString(36)}`;

const checks = [];
const check = (name, ok, detail = "") => checks.push({ name, ok: Boolean(ok), detail });

async function rows(session) {
  return session.eval(`(() => [...document.querySelectorAll("[data-audit-row]")].map((tr) => ({
    event: tr.dataset.auditEvent,
    label: tr.querySelector("[data-audit-event-label]")?.textContent ?? "",
    link: tr.querySelector("[data-audit-entity-link]")?.getAttribute("href") ?? null,
    entity: (tr.querySelector("[data-audit-entity-link], [data-audit-entity-label]")?.textContent ?? "").trim(),
    changes: [...tr.querySelectorAll("[data-audit-changes] li")].map((li) => li.textContent.trim()),
  })))()`);
}

async function waitForRows(session, predicate, attempts = 20) {
  for (let i = 0; i < attempts; i += 1) {
    const found = await rows(session);
    if (predicate(found)) return found;
    await sleep(250);
  }
  return rows(session);
}

const { session, close } = await openBrowser({ port: PORT, profile: PROFILE });
try {
  await session.navigate(`${baseUrl}/login`, 800);
  const status = await session.login(baseUrl, email, password);
  check("signed in", status === 200 || status === 204 || status === true, `login → ${status}`);

  // 1. a real diff to look for: create, then rename, a label.
  const renamed = await session.eval(`(async () => {
    const post = await fetch("/api/v1/labels", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: ${JSON.stringify(tag)} }) });
    if (!post.ok) return { error: "create " + post.status };
    const label = await post.json();
    const patch = await fetch("/api/v1/labels/" + label.id, { method: "PATCH", headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: ${JSON.stringify(tag + "-renamed")} }) });
    return { ok: patch.ok, status: patch.status, id: label.id };
  })()`);
  check("label renamed through the API", renamed.ok, JSON.stringify(renamed));

  // 2. the row, by URL filter.
  await session.navigate(`${baseUrl}/settings/audit?entity=label&q=${encodeURIComponent(tag)}`, 1500);
  const labelRows = await waitForRows(session, (r) => r.some((x) => x.event === "label.updated"));
  const row = labelRows.find((x) => x.event === "label.updated");
  check("audit page lists the label.updated row for the tag", Boolean(row), JSON.stringify(labelRows.slice(0, 3)));
  check("row reads the registry label, not the wire string", row?.label === "Label updated", row?.label);
  check("entity label is the label's name at write time", row?.entity === `${tag}-renamed`, row?.entity);
  check("entity links to Settings → Labels", row?.link?.endsWith("/settings/labels"), String(row?.link));
  check(
    "diff reads Name: old → new",
    row?.changes.some((c) => c.startsWith("Name:") && c.includes(tag) && c.includes(`${tag}-renamed`)),
    JSON.stringify(row?.changes),
  );
  check("the created row is there too", labelRows.some((x) => x.event === "label.created"), "");
  await session.screenshot(resolve("scripts", "audit-proof-label.png"));

  // 3. changed-field filter: every row's diff mentions Name.
  await session.navigate(`${baseUrl}/settings/audit?field=name`, 1500);
  const fieldRows = await waitForRows(session, (r) => r.length > 0);
  check("changed-field filter returns rows", fieldRows.length > 0, String(fieldRows.length));
  check(
    "every row under ?field=name changed the Name",
    fieldRows.every((x) => x.changes.some((c) => /^Name/.test(c))),
    JSON.stringify(fieldRows.filter((x) => !x.changes.some((c) => /^Name/.test(c))).slice(0, 2)),
  );

  // 4. items link to issues.
  await session.navigate(`${baseUrl}/settings/audit?entity=item`, 1500);
  const itemRows = await waitForRows(session, (r) => r.length > 0);
  check("item filter returns rows", itemRows.length > 0, String(itemRows.length));
  check(
    "an item row links to its issue page",
    itemRows.some((x) => x.link && /\/issues\/[A-Z0-9]+-\d+$/.test(x.link)),
    JSON.stringify(itemRows.slice(0, 2).map((x) => x.link)),
  );
  check("every item row is about an item", itemRows.every((x) => x.link === null || x.link.includes("/issues/")), "");

  // 5. the URL is the state: the filter bar reflects it after a reload.
  await session.navigate(`${baseUrl}/settings/audit?entity=label&source=people`, 1500);
  const selected = await session.eval(`(() => {
    const filters = document.querySelector("[data-audit-filters]");
    return filters ? filters.textContent : "";
  })()`);
  check("filter bar shows the URL's entity and source", /Label/.test(selected) && /People/.test(selected), selected.slice(0, 120));
  await session.screenshot(resolve("scripts", "audit-proof-page.png"), { fullPage: true });
} finally {
  await close();
}

const failed = report(
  Object.fromEntries(checks.map((c) => [c.ok ? c.name : `${c.name} — ${c.detail}`, c.ok])),
  { proof: "audit-proof", tag },
);
process.exit(failed ? 1 : 0);

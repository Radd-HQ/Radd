/**
 * RADD-1499: the Automation account is a service account, and the ledger treats it as one.
 *
 * The bug was invisible to tsc and pytest's unit layer: the seeded row had `source = local`,
 * so every people picker offered "Automation" as a colleague and the audit page's
 * Source = People listed the VCS connector's writes (attributed to it, `automated` false).
 * This drives a signed-in browser against a running Radd and asserts what an admin sees:
 *
 *   1. the directory returns Automation as `service`, Source = People has none of its rows,
 *      Source = System has them with `actor.machine`, and PATCH {active:false} is a 409;
 *   2. Settings → Audit log with Source = System draws its rows as machine rows (the server
 *      glyph, no avatar) — `[data-audit-machine-actor]`;
 *   3. the Who picker lists "Automation" with the "Service account" hint.
 *
 * Usage: node scripts/automation-account-proof.mjs [--base <url>] [email] [password]
 */
import { resolve } from "node:path";
import { outputPath, sleep, waitForSelector } from "./lib/cdp.mjs";
import { startProof } from "./lib/proof.mjs";

const { session, close, check, finish, baseUrl } = await startProof({
  port: 9493, profile: resolve(process.env.TMPDIR || "/tmp", "radd-automation-account-proof"),
  base: "http://127.0.0.1:8000",
});
try {
  // 1. the API facts the page is built from.
  const facts = await session.eval(`(async () => {
    const get = async (path) => {
      const r = await fetch("/api/v1" + path, { credentials: "include" });
      return { status: r.status, body: await r.json().catch(() => null) };
    };
    const dir = await get("/users/directory?q=Automation");
    const automation = (dir.body || []).find((u) => u.name === "Automation") || null;
    const id = automation?.id;
    const people = await get("/audit?source=people&actor_id=" + id + "&limit=5");
    const system = await get("/audit?source=system&actor_id=" + id + "&limit=5");
    const patch = await fetch("/api/v1/users/" + id, { method: "PATCH", credentials: "include",
      headers: { "content-type": "application/json" }, body: JSON.stringify({ active: false }) });
    const accounts = await get("/service-accounts?q=Automation");
    return {
      automation, id,
      peopleCount: (people.body || []).length,
      systemRows: (system.body || []).slice(0, 3).map((r) => ({ actor: r.actor, automated: r.automated, event: r.event_type })),
      patchStatus: patch.status,
      account: (accounts.body || []).find((a) => a.name === "Automation") || null,
    };
  })()`);
  check("the directory returns Automation as a service account", facts.automation?.source === "service", JSON.stringify(facts.automation));
  check("Source = People has no Automation rows", facts.peopleCount === 0, String(facts.peopleCount));
  check("Source = System carries its connector rows, marked machine and not automated",
    facts.systemRows.length > 0 && facts.systemRows.every((r) => r.actor?.machine === true && r.automated === false),
    JSON.stringify(facts.systemRows));
  check("deactivating the built-in account is refused (409)", facts.patchStatus === 409, String(facts.patchStatus));
  check("the service-accounts list marks it built-in", facts.account?.builtin === true, JSON.stringify(facts.account));

  // 2. the ledger, Source = System: Automation's rows are machine rows, not people.
  await session.navigate(`${baseUrl}/settings/audit?source=system&actor=${facts.id}`, 1500);
  await waitForSelector(session, "[data-audit-row]");
  const rows = await session.eval(`(() => [...document.querySelectorAll("[data-audit-row]")].map((tr) => {
    const who = tr.querySelector("td:nth-child(2)");
    return { machine: who?.querySelector("[data-audit-machine-actor]")?.dataset.auditMachineActor ?? null,
      glyphs: who?.querySelectorAll("svg").length ?? 0, text: (who?.textContent ?? "").trim(),
      avatarImg: Boolean(who?.querySelector("img")) };
  }))()`);
  await session.screenshot(outputPath("automation-account-proof-ledger.png"));
  check("the page lists Automation's rows under Source = System", rows.length > 0, String(rows.length));
  check("every row is drawn as a machine row (server glyph, no avatar)",
    rows.every((r) => r.machine === facts.id && r.glyphs === 1 && !r.avatarImg && /Automation/.test(r.text)),
    JSON.stringify(rows.slice(0, 3)));

  // 3. the Who picker: "Automation · Service account".
  await session.eval(`(() => { const b = [...document.querySelectorAll("button[aria-label='Filter by person']")][0]; b?.click(); return Boolean(b); })()`);
  await waitForSelector(session, "[role=dialog] input");
  await session.eval(`(() => { const i = document.querySelector("[role=dialog] input");
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    set.call(i, "Automation"); i.dispatchEvent(new Event("input", { bubbles: true })); })()`);
  await sleep(1200);
  const choices = await session.eval(`(() => [...document.querySelectorAll("[role=dialog] li button")].map((b) => ({
    text: b.textContent.trim(), hint: b.querySelector("[data-directory-hint]")?.textContent ?? null })))()`);
  const automationChoice = choices.find((c) => c.text.startsWith("Automation"));
  check("the Who picker offers Automation", Boolean(automationChoice), JSON.stringify(choices.slice(0, 5)));
  check("…qualified as a service account", automationChoice?.hint === "Service account", JSON.stringify(automationChoice));
  check("no console errors", session.consoleErrors.length === 0, JSON.stringify(session.consoleErrors.slice(0, 3)));
} finally {
  close();
}
finish({ baseUrl });

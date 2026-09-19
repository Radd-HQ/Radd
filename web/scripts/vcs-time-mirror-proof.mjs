#!/usr/bin/env node
/**
 * Proof for the MR/PR time mirror + the one Version control page (RADD-1257:
 * RADD-1258 seam, RADD-1259 GitLab, RADD-1262 settings):
 *
 *   node web/scripts/vcs-time-mirror-proof.mjs http://127.0.0.1:8000 admin@example.com change-me GLT-1
 *
 *   1. /settings/vcs shows ONE page with three host tabs; `?host=gitlab` selects
 *      the GitLab tab (aria-selected) and the old /settings/github path redirects
 *      to the GitHub tab;
 *   2. the GitLab tab lists the connection, its repository with a project AND a
 *      work-category select, and a Time-tracking identities section whose
 *      mapped list shows the email-matched account;
 *   3. the issue's Work log tab shows entries badged "from GitLab";
 *   4. the rail's time-tracking panel renders those rows with Edit/Delete
 *      DISABLED (spec-96 treatment) and a reason on hover, while a hand-logged
 *      row keeps its controls enabled;
 *   5. /timesheet badges the mirrored rows too.
 *
 * Expects the live fixture the setup script left behind: an item <key> whose
 * project logs time, with at least one mirrored GitLab worklog, and a GitLab
 * connection with one identity mapped. Read-only except for one hand-logged
 * worklog on the item, which is deleted at the end.
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword, itemKey] = process.argv.slice(2);
if (!baseUrl || !adminEmail || !adminPassword || !itemKey) {
  console.error("usage: vcs-time-mirror-proof.mjs <baseUrl> <adminEmail> <adminPassword> <itemKey>");
  process.exit(2);
}
const PORT = 9512;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-vcs-time-mirror-proof");
const SHOTS = resolve(process.cwd(), "web/scripts");

const API = `
  const api = async (method, path, body) => {
    const r = await fetch("/api/v1" + path, { method, headers: { "content-type": "application/json" }, credentials: "same-origin", body: body === undefined ? undefined : JSON.stringify(body) });
    const text = await r.text();
    return { status: r.status, body: text ? JSON.parse(text) : null };
  };
`;

async function main() {
  const { session, close } = await openBrowser({ port: PORT, profile: PROFILE, width: 1500, height: 1000 });
  const waitFor = async (selector, timeoutMs = 12000) => {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      if (await session.eval(`Boolean(document.querySelector(${JSON.stringify(selector)}))`)) return true;
      await sleep(250);
    }
    return false;
  };
  const checks = {};
  const context = { itemKey };
  let handLogged = null;
  try {
    await session.navigate(baseUrl + "/login", 800);
    context.login = await session.login(baseUrl, adminEmail, adminPassword);

    // --- 1. one page, three tabs, URL-carried ---
    await session.navigate(`${baseUrl}/settings/vcs?host=gitlab`, 2500);
    await waitFor('[role="tablist"][aria-label="Version control hosts"]');
    const tabs = await session.eval(`(() => {
      const list = document.querySelector('[role="tablist"][aria-label="Version control hosts"]');
      const items = [...(list?.querySelectorAll('[role="tab"]') ?? [])];
      return { count: items.length, labels: items.map((t) => t.textContent.trim().replace(/off$/, "")), selected: items.find((t) => t.getAttribute("aria-selected") === "true")?.textContent.trim(),
        navEntries: [...document.querySelectorAll('aside a, nav a')].map((a) => a.textContent.trim()).filter((t) => /^(Forgejo|GitHub|GitLab|Version control)$/.test(t)) };
    })()`);
    context.tabs = tabs;
    checks.threeTabs = tabs.count === 3 && tabs.labels.join(",") === "Forgejo,GitHub,GitLab";
    checks.gitlabTabSelectedFromUrl = tabs.selected === "GitLab";
    checks.oneNavEntry = tabs.navEntries.length === 1 && tabs.navEntries[0] === "Version control";

    await session.navigate(`${baseUrl}/settings/github`, 2500);
    await waitFor('[role="tablist"][aria-label="Version control hosts"]');
    const redirected = await session.eval(`({ path: location.pathname, search: location.search, selected: document.querySelector('[role="tab"][aria-selected="true"]')?.textContent.trim() })`);
    context.redirected = redirected;
    checks.oldGithubPathRedirectsToTab = redirected.path.endsWith("/settings/vcs") && redirected.search.includes("host=github") && redirected.selected === "GitHub";

    // --- 2. the GitLab tab's body ---
    await session.navigate(`${baseUrl}/settings/vcs?host=gitlab`, 2500);
    await waitFor('[aria-label^="Work category for time mirrored from"]');
    // The identities card is collapsed by default when nothing is unmatched — open it.
    await session.eval(`(() => { const b = [...document.querySelectorAll('button[aria-expanded]')].find((x) => /Time-tracking identities/i.test(x.textContent)); if (b && b.getAttribute("aria-expanded") === "false") b.click(); })()`);
    await sleep(600);
    const gitlabTab = await session.eval(`(() => {
      const text = document.body.innerText;
      const categorySelects = document.querySelectorAll('[aria-label^="Work category for time mirrored from"]');
      const projectSelects = document.querySelectorAll('[aria-label^="Project for "]');
      return {
        hasConnection: /Cinesite GitLab|GitLab/.test(text) && document.querySelectorAll('section header').length >= 1,
        repos: [...document.querySelectorAll('.font-mono')].map((n) => n.textContent.trim()).filter((t) => t.includes("/")),
        categorySelects: categorySelects.length, projectSelects: projectSelects.length,
        identitiesOpen: /mapped accounts/i.test(text),
        mappedRow: /matched by email/.test(text),
        mappedNames: [...document.querySelectorAll('li')].map((li) => li.innerText.replace(/\\s+/g, " ").trim()).filter((t) => /matched by email|mapped by hand/.test(t)),
        unmatchedEmpty: /Every account that logged time is matched/.test(text),
      };
    })()`);
    context.gitlabTab = gitlabTab;
    checks.gitlabTabListsRepoWithProjectAndCategory = gitlabTab.repos.length >= 1 && gitlabTab.categorySelects >= 1 && gitlabTab.projectSelects >= 1;
    checks.identityMapShowsEmailMatch = gitlabTab.identitiesOpen && gitlabTab.mappedRow;
    checks.noUnmatchedAuthors = gitlabTab.unmatchedEmpty;
    await session.screenshot(resolve(SHOTS, "vcs-time-mirror-proof-settings.png"));

    // --- 3 + 4. the issue: badges in the Work log tab, disabled controls in the rail ---
    handLogged = await session.eval(`(async () => { ${API}
      const item = await api("GET", "/items/by-key/" + ${JSON.stringify(itemKey)});
      const itemId = item.body?.id;
      const w = await api("POST", "/items/" + itemId + "/worklogs", { time_spent: "15m", note: "hand-logged for the proof" });
      return { itemId, worklogId: w.body?.id, status: w.status };
    })()`);
    context.handLogged = handLogged;
    await session.navigate(`${baseUrl}/issues/${itemKey}`, 3000);
    // Open the Work log tab (activity panel), if present, and EXPAND the rail's
    // Time tracking section — its collapsed face shows totals only.
    await session.eval(`(() => { const t = [...document.querySelectorAll('[role="tab"]')].find((x) => /work ?log/i.test(x.textContent)); t?.click(); })()`);
    await session.eval(`(() => { const b = [...document.querySelectorAll('button[aria-expanded="false"]')].find((x) => /time tracking/i.test(x.textContent)); b?.click(); })()`);
    await sleep(900);
    const issue = await session.eval(`(() => {
      const badges = [...document.querySelectorAll('span')].filter((s) => /^from GitLab$/.test(s.textContent.trim()));
      const edits = [...document.querySelectorAll('button[aria-label="Edit worklog"]')];
      const deletes = [...document.querySelectorAll('button[aria-label="Delete worklog"]')];
      const rows = edits.map((b) => { const li = b.closest("li"); const wrap = b.closest("span[title]"); return { mirrored: Boolean(li?.querySelector('span[title^="Mirrored from"]')), disabled: b.disabled, reason: wrap?.getAttribute("title") || "" }; });
      return { badges: badges.length, edits: edits.length, deletes: deletes.length, rows };
    })()`);
    context.issue = issue;
    checks.workLogBadgesMirroredRows = issue.badges >= 2;
    const mirroredRows = issue.rows.filter((r) => r.mirrored);
    const plainRows = issue.rows.filter((r) => !r.mirrored);
    context.mirroredRows = mirroredRows.length;
    context.plainRows = plainRows.length;
    checks.mirroredControlsDisabledWithReason = mirroredRows.length >= 1 && mirroredRows.every((r) => r.disabled && /change it there/i.test(r.reason));
    checks.handLoggedRowStaysEditable = plainRows.length >= 1 && plainRows.every((r) => !r.disabled);
    await session.screenshot(resolve(SHOTS, "vcs-time-mirror-proof-issue.png"));

    // The server refuses too — the UI treatment is not the only guard.
    const refusal = await session.eval(`(async () => { ${API}
      const item = await api("GET", "/items/by-key/" + ${JSON.stringify(itemKey)});
      const tl = await api("GET", "/items/" + item.body.id + "/timelog");
      const mirrored = tl.body.entries.find((e) => e.external_source);
      const patch = await api("PATCH", "/worklogs/" + mirrored.id, { time_spent: "1h" });
      const del = await api("DELETE", "/worklogs/" + mirrored.id);
      return { patch: patch.status, del: del.status, detail: patch.body?.detail };
    })()`);
    context.refusal = refusal;
    checks.serverRefusesEditingMirroredRows = refusal.patch === 409 && refusal.del === 409;

    // --- 5. the timesheet ---
    await session.navigate(`${baseUrl}/timesheet`, 3000);
    const sheet = await session.eval(`(() => {
      // expand the first group row so its entries render
      const row = document.querySelector('tbody tr');
      row?.click();
      return { groupRows: document.querySelectorAll('tbody tr').length };
    })()`);
    await sleep(700);
    const timesheet = await session.eval(`(() => ({ badges: [...document.querySelectorAll('span')].filter((s) => /^from GitLab$/.test(s.textContent.trim())).length, rows: document.querySelectorAll('tbody tr').length }))()`);
    context.timesheet = timesheet;
    checks.timesheetBadgesMirroredRows = timesheet.badges >= 1;
    await session.screenshot(resolve(SHOTS, "vcs-time-mirror-proof-timesheet.png"));
    context.sheet = sheet;
  } finally {
    if (handLogged?.worklogId) {
      await session.eval(`(async () => { ${API} await api("DELETE", "/worklogs/" + ${JSON.stringify(handLogged.worklogId)}); })()`).catch(() => {});
    }
    process.exitCode = report(checks, context) ? 1 : 0;
    close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

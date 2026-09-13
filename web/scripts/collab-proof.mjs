#!/usr/bin/env node
/**
 * Spec 122 proof (RADD-1163): two people edit one page, a third reads it.
 *
 *   node web/scripts/collab-proof.mjs http://localhost:8000 admin@example.com change-me
 *
 * Three real browsers (three profiles, three debug ports): Ada and Grace edit,
 * the admin reads. Measured, never eyeballed:
 *   - what Ada types appears in Grace's editor, and the reverse, within 5 s;
 *   - each sees the other's cursor and the header counts "2 editing";
 *   - the reader sees "2 editing" and, after the autosave, the typed text;
 *   - a PATCH from outside the room is refused 409 while they edit and
 *     accepted once both are done;
 *   - the session added at most two history rows (seed + final), not one
 *     per pause in typing;
 *   - a mid-session reload rejoins with the document intact.
 * A server restart resuming a stored state is NOT driven here — it needs the
 * dev stack restarted around the run; see the issue.
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
if (!baseUrl || !adminEmail || !adminPassword) {
  console.error("usage: collab-proof.mjs <baseUrl> <adminEmail> <adminPassword>");
  process.exit(2);
}
const PROFILE = (name) => resolve(process.env.TMPDIR || "/tmp", `radd-collab-proof-${name}`);
const STAMP = Date.now().toString(36).slice(-5);
const PEOPLE = {
  ada: { email: "collab-proof-ada@example.test", name: "Ada Proof", password: "collab-proof-1" },
  grace: { email: "collab-proof-grace@example.test", name: "Grace Proof", password: "collab-proof-1" },
};
const SEED_BODY = "The page before anyone edited it.";

const API = `
  const api = async (method, path, body) => {
    const r = await fetch("/api/v1" + path, {
      method, credentials: "include", headers: { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await r.text();
    return { status: r.status, body: text ? JSON.parse(text) : null };
  };
`;

/** Poll `probe` (a page expression) until it returns a truthy value. */
async function until(session, expression, { timeoutMs = 5000, everyMs = 200 } = {}) {
  const start = Date.now();
  for (;;) {
    const value = await session.eval(expression);
    if (value) return value;
    if (Date.now() - start > timeoutMs) return value;
    await sleep(everyMs);
  }
}

const EDITOR = `document.querySelector(".ProseMirror")`;
const EDITOR_TEXT = `(${EDITOR}?.innerText ?? "")`;
const PRESENCE = `(document.querySelector('[aria-label^="In this page:"]')?.getAttribute("aria-label") ?? "")`;
const REMOTE_CURSORS = `document.querySelectorAll(".ProseMirror-yjs-cursor").length`;

async function enterEdit(session) {
  await session.click("button", (t) => t.trim() === "Edit page");
  // The room is joined and the document bound once the editor is editable.
  await until(session, `${EDITOR}?.getAttribute("contenteditable") === "true"`, { timeoutMs: 8000 });
}

async function typeAtEnd(session, text) {
  await session.eval(`(() => {
    const view = ${EDITOR};
    view.focus();
    const range = document.createRange();
    range.selectNodeContents(view);
    range.collapse(false);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  })()`);
  await session.send("Input.insertText", { text });
}

async function main() {
  const admin = await openBrowser({ port: 9491, profile: PROFILE("admin"), width: 1400, height: 900 });
  const ada = await openBrowser({ port: 9492, profile: PROFILE("ada"), width: 1400, height: 900 });
  const grace = await openBrowser({ port: 9493, profile: PROFILE("grace"), width: 1400, height: 900 });
  const checks = {};
  const context = {};
  try {
    // --- setup as the admin: two editors, a space, a page ---
    await admin.session.navigate(baseUrl + "/login", 800);
    await admin.session.login(baseUrl, adminEmail, adminPassword);
    const setup = await admin.session.eval(`(async () => { ${API}
      const me = (await api("GET", "/auth/me")).body;
      const ensure = async (person) => {
        const found = (await api("GET", "/users?q=" + encodeURIComponent(person.email))).body;
        const stale = Array.isArray(found) ? found.find((u) => u.email === person.email) : null;
        if (stale) await api("DELETE", "/users/" + stale.id + "?reassign_to=" + me.id);
        return (await api("POST", "/users", { ...person, instance_role: "admin" })).body;
      };
      const people = { ada: await ensure(${JSON.stringify(PEOPLE.ada)}), grace: await ensure(${JSON.stringify(PEOPLE.grace)}) };
      const space = (await api("POST", "/page-spaces", { slug: "collab-${STAMP}", name: "Collab proof ${STAMP}" })).body;
      const page = (await api("POST", "/pages", { space_id: space.id, title: "Shared page", body: ${JSON.stringify(SEED_BODY)} })).body;
      const versions = (await api("GET", "/pages/" + page.id + "/versions")).body;
      return { space, page, people, versionsBefore: Array.isArray(versions) ? versions.length : -1 };
    })()`);
    const { space, page } = setup;
    context.page = { id: page.id, versionsBefore: setup.versionsBefore };
    checks.setupCreated = Boolean(space?.id && page?.id && setup.people.ada?.id && setup.people.grace?.id);
    const pageUrl = `${baseUrl}/pages/${space.slug}/${page.slug}`;

    // --- the two editors sign in and open the page ---
    for (const [who, browser] of [["ada", ada], ["grace", grace]]) {
      await browser.session.navigate(baseUrl + "/login", 800);
      const status = await browser.session.login(baseUrl, PEOPLE[who].email, PEOPLE[who].password);
      context[`${who}LoginStatus`] = status;
      checks[`${who}SignedIn`] = status >= 200 && status < 300;
    }
    await ada.session.navigate(pageUrl, 2500);
    await grace.session.navigate(pageUrl, 2500);
    await admin.session.navigate(pageUrl, 2500);

    // --- both enter edit mode: one seeds, the other syncs ---
    await enterEdit(ada.session);
    await enterEdit(grace.session);
    const adaSeeded = await until(ada.session, `${EDITOR_TEXT}.includes(${JSON.stringify(SEED_BODY)})`);
    const graceSynced = await until(grace.session, `${EDITOR_TEXT}.includes(${JSON.stringify(SEED_BODY)})`);
    checks.bothSeeTheSeededBody = adaSeeded === true && graceSynced === true;
    const graceCount = await grace.session.eval(`(${EDITOR_TEXT}.match(/${SEED_BODY.slice(0, 12)}/g) || []).length`);
    checks.seededExactlyOnce = graceCount === 1;

    // --- who saves? (the election is random, so the proof reads it) ---
    const SAVER = `(document.querySelector("[data-collab-saver]")?.getAttribute("data-collab-saver") ?? "absent")`;
    const RECORD_PATCHES = `(() => { if (window.__patches) return "armed"; window.__patches = [];
      const original = window.fetch; window.fetch = (url, init) => { if (init && init.method === "PATCH") window.__patches.push(String(init.body || "")); return original(url, init); };
      return "armed"; })()`;
    await ada.session.eval(RECORD_PATCHES);
    await grace.session.eval(RECORD_PATCHES);
    await sleep(1500);
    const saverIs = { ada: await ada.session.eval(SAVER), grace: await grace.session.eval(SAVER) };
    context.saver = saverIs;
    checks.exactlyOneSaver = [saverIs.ada, saverIs.grace].filter((v) => v === "true").length === 1;
    const saver = saverIs.ada === "true" ? ada : grace;
    const other = saver === ada ? grace : ada;

    // --- typing flows both ways: the SAVER first (it saves its own line),
    //     then the other person — whose text the saver must ALSO save ---
    const saverLine = ` The saver wrote this ${STAMP}.`;
    const otherLine = ` The other one answered ${STAMP}.`;
    const t1 = Date.now();
    await typeAtEnd(saver.session, saverLine);
    const saverSeenByOther = await until(other.session, `${EDITOR_TEXT}.includes(${JSON.stringify(saverLine.trim())})`);
    context.saverToOtherMs = Date.now() - t1;
    checks.saverTextReachesOther = saverSeenByOther === true;
    const firstSave = await until(admin.session, `(async () => { ${API}
      return (await api("GET", "/pages/${page.id}")).body.body.includes(${JSON.stringify(saverLine.trim())});
    })()`, { timeoutMs: 8000, everyMs: 500 });
    checks.saverOwnLineAutosaved = firstSave === true;
    const t2 = Date.now();
    await typeAtEnd(other.session, otherLine);
    const otherSeenBySaver = await until(saver.session, `${EDITOR_TEXT}.includes(${JSON.stringify(otherLine.trim())})`);
    context.otherToSaverMs = Date.now() - t2;
    checks.otherTextReachesSaver = otherSeenBySaver === true;
    const secondSave = await until(admin.session, `(async () => { ${API}
      return (await api("GET", "/pages/${page.id}")).body.body.includes(${JSON.stringify(otherLine.trim())});
    })()`, { timeoutMs: 8000, everyMs: 500 });
    checks.otherLineAutosavedBySaver = secondSave === true;
    context.patchBodies = { saver: await saver.session.eval(`window.__patches`), other: await other.session.eval(`window.__patches`) };
    const adaLine = saver === ada ? saverLine : otherLine;
    const graceLine = saver === grace ? saverLine : otherLine;

    // --- cursors and presence ---
    checks.adaSeesGraceCursor = (await until(ada.session, `${REMOTE_CURSORS} >= 1`)) === true;
    checks.graceSeesAdaCursor = (await until(grace.session, `${REMOTE_CURSORS} >= 1`)) === true;
    const adaPresence = await until(ada.session, `${PRESENCE}.includes("editing") ? ${PRESENCE} : ""`);
    context.presenceSeenByAda = adaPresence;
    checks.editorsSeeTwoEditing = typeof adaPresence === "string" && adaPresence.includes("2 editing");
    const readerPresence = await until(admin.session, `${PRESENCE}.includes("2 editing") ? ${PRESENCE} : ""`, { timeoutMs: 8000 });
    context.presenceSeenByReader = readerPresence;
    checks.readerSeesTwoEditing = typeof readerPresence === "string" && readerPresence.includes("2 editing");

    // --- the reader gets the saved text through the autosave + realtime ---
    const readerSees = await until(
      admin.session,
      `document.body.innerText.includes(${JSON.stringify(otherLine.trim())})`,
      { timeoutMs: 12000, everyMs: 500 },
    );
    checks.readerSeesSavedText = readerSees === true;

    // --- nothing publishes over live work ---
    const outside = await admin.session.eval(`(async () => { ${API}
      return (await api("PATCH", "/pages/${page.id}", { body: "an outside write" })).status;
    })()`);
    context.outsideWriteWhileEditing = outside;
    checks.outsideWriteRefusedWhileEditing = outside === 409;

    // --- reload mid-session: Grace comes back to the same document ---
    await grace.session.navigate(pageUrl, 2500);
    await enterEdit(grace.session);
    const afterReload = await until(grace.session, `${EDITOR_TEXT}.includes(${JSON.stringify(adaLine.trim())}) && ${EDITOR_TEXT}.includes(${JSON.stringify(graceLine.trim())})`);
    checks.reloadRejoinsIntact = afterReload === true;

    // --- both leave; the outside write now succeeds; history stayed short ---
    await ada.session.click("button", (t) => t.trim() === "Done");
    await sleep(1500);
    await grace.session.click("button", (t) => t.trim() === "Done");
    await sleep(2500);
    const after = await admin.session.eval(`(async () => { ${API}
      const versions = (await api("GET", "/pages/${page.id}/versions")).body;
      const saved = (await api("GET", "/pages/${page.id}")).body;
      const write = (await api("PATCH", "/pages/${page.id}", { body: saved.body + "\\n\\nAfter the session." })).status;
      return { versions: Array.isArray(versions) ? versions.length : -1, body: saved.body, write };
    })()`);
    context.versionsAfter = after.versions;
    context.savedBody = after.body;
    context.outsideWriteAfter = after.write;
    checks.savedBodyHoldsEveryLine = [saverLine, otherLine].every((line) => after.body.includes(line.trim()));
    checks.outsideWriteAcceptedAfter = after.write === 200;
    const grew = after.versions - setup.versionsBefore;
    context.historyRowsAdded = grew;
    checks.historyCoalesced = grew >= 1 && grew <= 2;
    context.consoleErrors = { ada: ada.session.consoleErrors.slice(0, 5), grace: grace.session.consoleErrors.slice(0, 5) };
  } finally {
    await Promise.all([admin.close(), ada.close(), grace.close()]);
  }
  report(checks, context);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

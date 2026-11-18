#!/usr/bin/env node
/**
 * RADD-1575 proof — logging time from My Work, in a real browser against a real backend.
 *
 *   1. My Work offers a "Log time" widget to someone the Timesheet is offered to
 *   2. it lists an issue assigned to me, with a duration field
 *   3. typing 45m and pressing Enter logs a real 45m worklog on it, dated today
 *   4. the widget's "Today" total and the ticket's own figure follow
 *   5. the widget fits its card: nothing scrolls sideways, text at the type scale's meta step or more
 *   6. at its default width a 40-character title is shown whole, with the reason under it (RADD-1579)
 *   7. someone whose My Work layout predates the widget is offered it once: Add appends it and
 *      moves nothing else, the offer does not come back, and "Not now" is remembered too
 *
 *   node web/scripts/log-time-widget-proof.mjs http://127.0.0.1:8000 admin@example.com change-me
 *
 * Creates a project with one issue and a user, and deletes them.
 */
import { resolve } from "node:path";
import { outputPath, PAGE_API, sleep } from "./lib/cdp.mjs";
import { startProof } from "./lib/proof.mjs";

const PORT = 9499;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-logtime-widget-proof");
const STAMP = Date.now().toString(36);
const KEY = `LW${STAMP.slice(-4).toUpperCase()}`;
const TITLE = "grade the trailer for the festival cut 2"; // 40 characters
const seconds = (text) => { let s = 0; for (const [, n, u] of text.matchAll(/(\d+)(h|m)/g)) s += Number(n) * (u === "h" ? 3600 : 60); return s; };

async function main() {
  const { session, close, baseUrl, email, password, finish, check } = await startProof({ port: PORT, profile: PROFILE, width: 1440, height: 1000 });
  const context = { key: KEY };
  let projectId = null;
  let userId = null;
  try {
    const setup = await session.eval(`(async () => { ${PAGE_API}
      const me = (await api("GET", "/auth/me")).body;
      const project = (await api("POST", "/projects", { key: ${JSON.stringify(KEY)}, name: "Log time widget proof" })).body;
      await api("PUT", "/projects/" + project.id + "/timelogging", { enabled: true });
      const item = (await api("POST", "/items", { project_id: project.id, title: ${JSON.stringify(TITLE)}, assignee_id: me.id })).body;
      return { project, item };
    })()`);
    projectId = setup.project?.id ?? null;
    const { item } = setup;

    await session.navigate(`${baseUrl}/`, 2500);
    let present = false;
    for (let i = 0; i < 60 && !present; i += 1) { await sleep(150); present = await session.eval(`Boolean(document.querySelector("[data-log-time-widget] [data-quick-log='${item.key}']"))`); }
    check("My Work has a Log time widget listing the issue assigned to me, with a duration field", present);
    if (!present) throw new Error("no widget: nothing else can be measured");

    const READ = `(() => { const w = document.querySelector("[data-log-time-widget]"); const row = w.querySelector("[data-tray-row='${item.key}']"); const title = row.querySelector("[data-tray-ticket] > span"); const why = row.querySelector("[data-ticket-why]"); return {
      title: { text: title.textContent, cut: Math.max(title.scrollWidth - title.clientWidth, title.scrollHeight - title.clientHeight), width: title.clientWidth, row: row.clientWidth, top: title.getBoundingClientRect().top },
      whyTop: why ? why.getBoundingClientRect().top : null, card: w.clientWidth,
      today: w.querySelector("[data-log-time-today]").textContent, why: w.querySelector("[data-tray-row='${item.key}'] [data-ticket-why]")?.textContent ?? "",
      overflow: w.scrollWidth - w.clientWidth, minFont: Math.min(...[...w.querySelectorAll("*")].filter((n) => n.childElementCount === 0 && n.textContent.trim()).map((n) => parseFloat(getComputedStyle(n).fontSize))) }; })()`;
    const before = await session.eval(READ);
    await session.eval(`(() => { const n = document.querySelector("[data-log-time-widget] [data-quick-log='${item.key}']"); n.scrollIntoView({ block: "center" }); n.focus(); return true; })()`);
    await session.send("Input.insertText", { text: "45m" });
    await session.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
    await session.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
    let after = before;
    for (let i = 0; i < 60; i += 1) { await sleep(150); after = await session.eval(READ); if (seconds(after.today) === seconds(before.today) + 2700 && /45m/.test(after.why)) break; }
    const stored = await session.eval(`(async () => { ${PAGE_API}
      const log = (await api("GET", "/items/${item.id}/timelog")).body;
      const now = new Date(); const today = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" + String(now.getDate()).padStart(2, "0");
      return { today, worklogs: (log.entries ?? []).map((w) => ({ on: w.worked_on, seconds: w.time_spent_seconds })) };
    })()`);
    context.stored = stored;
    check("typing 45m and pressing Enter logs a 45m worklog on the issue, dated today", stored.worklogs.length === 1 && stored.worklogs[0].seconds === 2700 && stored.worklogs[0].on === stored.today, JSON.stringify(stored));
    check("the widget's Today total goes up by 45m", seconds(after.today) === seconds(before.today) + 2700, `${before.today} -> ${after.today}`);
    check("the ticket's own figure shows it", /45m/.test(after.why), after.why);
    check("the widget fits its card with no sideways scroll", after.overflow <= 0, `overflow ${after.overflow}px`);
    check("no text in it is under the type scale's meta step (12px)", after.minFont >= 12, `${after.minFont}px`);
    check("a 40-character title is shown whole at the widget's default width, the reason on the line under it", after.title.text.trim() === TITLE && after.title.cut <= 0 && after.whyTop > after.title.top + 4, JSON.stringify({ ...after.title, whyTop: after.whyTop, card: after.card }));
    await session.screenshot(outputPath("log-time-widget-proof.png"));

    // 7 — a person whose layout predates the widget. A new user, so nobody's real My Work is touched.
    const person = await session.eval(`(async () => { ${PAGE_API}
      const user = (await api("POST", "/users", { email: "offer-${STAMP}@example.test", name: "Offer ${STAMP}", password: "change-me-too" })).body;
      // A worklog of theirs is what makes the Timesheet, and so the widget, theirs to be offered.
      const logged = (await api("POST", "/items/${item.id}/worklogs", { time_spent: "15m", worked_on: ${JSON.stringify(stored.today)}, author_id: user.id })).status;
      return { user, logged };
    })()`);
    userId = person.user?.id ?? null;
    await session.login(baseUrl, `offer-${STAMP}@example.test`, "change-me-too");
    const WIDGETS = "/dashboards/my-work/widgets", OFFERS = "/dashboards/my-work/offers";
    const before7 = await session.eval(`(async () => { ${PAGE_API}
      const suggested = (await api("GET", "${WIDGETS}")).body;
      const kept = suggested.filter((w) => w.widget_type !== "logtime");
      const saved = await api("PUT", "${WIDGETS}", { widgets: kept, expected: suggested });
      const afterRemoving = (await api("GET", "${OFFERS}")).body;
      // What a layout stored before the widget existed looks like: no record of any offer.
      await api("PUT", "/auth/me/preferences", { my_work_offers_seen: [] });
      const offered = (await api("GET", "${OFFERS}")).body;
      return { suggested: suggested.map((w) => w.widget_type), saved: saved.status, kept: kept.map((w) => w.id), afterRemoving: afterRemoving.length, offered: offered.map((w) => w.widget_type) };
    })()`);
    context.offer = before7;
    check("setup: the new person is suggested the widget and stores a layout without it", person.logged === 201 && before7.suggested.includes("logtime") && before7.saved === 200, JSON.stringify({ logged: person.logged, ...before7 }));
    check("someone who took the widget off themselves is not asked", before7.afterRemoving === 0, String(before7.afterRemoving));
    check("a layout that predates the widget gets the offer", JSON.stringify(before7.offered) === JSON.stringify(["logtime"]), JSON.stringify(before7.offered));

    const PAGE = `({ offer: document.querySelector("[data-widget-offer='logtime']")?.textContent ?? null, widget: Boolean(document.querySelector("[data-log-time-widget]")) })`;
    await session.navigate(`${baseUrl}/`, 2500);
    let page = {};
    for (let i = 0; i < 60; i += 1) { page = await session.eval(PAGE); if (page.offer) break; await sleep(150); }
    check("My Work says the widget is available, and has not added it", /Log time is now available on My Work/.test(page.offer ?? "") && page.widget === false, JSON.stringify(page));
    await session.eval(`document.querySelector("[data-widget-offer='logtime'] [data-widget-offer-add]").click()`);
    for (let i = 0; i < 60; i += 1) { page = await session.eval(PAGE); if (page.widget && !page.offer) break; await sleep(150); }
    const added = await session.eval(`(async () => { ${PAGE_API}
      const layout = (await api("GET", "${WIDGETS}")).body;
      return { ids: layout.map((w) => w.id), last: layout.at(-1)?.widget_type, offers: (await api("GET", "${OFFERS}")).body.length };
    })()`);
    check("Add puts the widget on the page and the offer away", page.widget === true && page.offer === null, JSON.stringify(page));
    check("…at the end of their layout, everything else where it was", added.last === "logtime" && JSON.stringify(added.ids.slice(0, -1)) === JSON.stringify(before7.kept), JSON.stringify(added));
    await session.navigate(`${baseUrl}/`, 2500);
    for (let i = 0; i < 40; i += 1) { page = await session.eval(PAGE); if (page.widget) break; await sleep(150); }
    const again = await session.eval(`(async () => { ${PAGE_API}
      const layout = (await api("GET", "${WIDGETS}")).body;
      const removed = await api("PUT", "${WIDGETS}", { widgets: layout.filter((w) => w.widget_type !== "logtime"), expected: layout });
      const afterRemoving = (await api("GET", "${OFFERS}")).body.length;
      // "Not now": the same starting point, answered the other way.
      await api("PUT", "/auth/me/preferences", { my_work_offers_seen: [] });
      const reopened = (await api("GET", "${OFFERS}")).body.length;
      const declined = await api("POST", "${OFFERS}/logtime", { accept: false });
      return { removed: removed.status, afterRemoving, reopened, declined: declined.status, layout: declined.body.map((w) => w.widget_type), offers: (await api("GET", "${OFFERS}")).body.length,
               unknown: (await api("POST", "${OFFERS}/assigned", { accept: true })).status };
    })()`);
    check("after a reload the widget is still there and the offer is not", page.widget === true && page.offer === null, JSON.stringify(page));
    check("taking the widget off again does not bring the offer back", again.removed === 200 && again.afterRemoving === 0, JSON.stringify(again));
    check("Not now adds nothing and is remembered", again.reopened === 1 && again.declined === 200 && !again.layout.includes("logtime") && again.offers === 0, JSON.stringify(again));
    check("only a type that is on offer can be answered", again.unknown === 404, String(again.unknown));
    await session.login(baseUrl, email, password);
  } finally {
    if (projectId) await session.eval(`(async () => { ${PAGE_API} await api("DELETE", "/projects/${projectId}"); return true; })()`).catch(() => null);
    if (userId) await session.eval(`(async () => { ${PAGE_API} await api("DELETE", "/users/${userId}"); return true; })()`).catch(() => null);
    await close();
  }
  finish(context);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

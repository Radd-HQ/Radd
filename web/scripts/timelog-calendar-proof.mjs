#!/usr/bin/env node
/**
 * RADD-1541 proof — a week of time entered from one screen, in a real browser against a real
 * backend. The pilot's complaint was that logging is harder than in the tool it replaces; the
 * done-when is that a person can enter a full day across several issues without opening one.
 *
 *   1. /timesheet opens on "My week": seven day columns, the trays above them
 *   2. dragging a ticket from the tray onto a day logs 1h there (a real worklog, read back)
 *   3. dragging the card to another day MOVES it; with Ctrl held it COPIES it
 *   4. pulling the card's bottom edge changes the duration in quarter hours
 *   5. double-clicking the duration and typing one sets it; double-clicking the body sets a note
 *   6. the keyboard does the same: + adds 15 minutes, Delete removes the card
 *   7. a category chip logs general time with no issue
 *   8. the day's Add row finds an issue by key and logs it — no mouse drag needed
 *   8b. a duration typed beside a ticket logs it on the highlighted day; a day's name picks the
 *       day; the tray's box finds an issue that is not on the list (RADD-1573)
 *   9. every day total and the week total are the sum of the cards on screen, at every step
 *  10. the Report tab shows the same entries
 *  11. the layout holds: no horizontal page scroll at 1440px, columns at least 150px, text 12px+
 *
 *   node web/scripts/timelog-calendar-proof.mjs http://127.0.0.1:8000 admin@example.com change-me
 *
 * Creates a throwaway project with three issues assigned to the signed-in user, and deletes the
 * project and every worklog it made.
 */
import { resolve } from "node:path";
import { outputPath, PAGE_API, sleep } from "./lib/cdp.mjs";
import { startProof } from "./lib/proof.mjs";

const PORT = 9497;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-timelog-proof");
const KEY = `TL${Date.now().toString(36).slice(-4).toUpperCase()}`;
const COLLEAGUE = `timelog-colleague-${Date.now().toString(36)}@example.test`;
const HOUR_PX = 44; // timelog/model.ts

/** Today as a local calendar date. */
const TODAY = (() => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
})();
/** The Monday-based week the page shows for today, as the page computes it (UTC date math). */
const week = (() => {
  const ms = Date.parse(`${TODAY}T00:00:00Z`);
  const monday = ms - ((new Date(ms).getUTCDay() + 6) % 7) * 86_400_000;
  return Array.from({ length: 7 }, (_, i) => new Date(monday + i * 86_400_000).toISOString().slice(0, 10));
})();
const [MON, TUE, WED, THU, FRI] = week;

/** What the week shows: per day the total the header prints and the cards under it. */
const STATE = `(() => {
  const seconds = (text) => { let s = 0; for (const [, n, u] of text.matchAll(/(\\d+)(h|m)/g)) s += Number(n) * (u === "h" ? 3600 : 60); return s; };
  const days = {};
  for (const day of document.querySelectorAll("[data-day]")) {
    const cards = [...day.querySelectorAll("[data-worklog]")].map((card) => ({
      id: card.dataset.worklog, key: card.dataset.worklogKey, seconds: Number(card.dataset.seconds),
      shown: seconds(card.querySelector("[data-duration]")?.textContent ?? ""), height: Math.round(card.getBoundingClientRect().height),
    }));
    days[day.dataset.day] = { header: seconds(day.querySelector("[data-day-total]").textContent), cards, load: day.dataset.dayLoad };
  }
  return { days, week: seconds(document.querySelector("[data-week-total]")?.textContent ?? "") };
})()`;

async function main() {
  const { session, close, baseUrl, email, password, finish, check } = await startProof({ port: PORT, profile: PROFILE, width: 1440, height: 1000 });
  const context = { key: KEY, week };
  let projectId = null;
  let offProjectId = null;
  let colleagueId = null;
  const made = new Set();
  try {
    const setup = await session.eval(`(async () => { ${PAGE_API}
      const me = (await api("GET", "/auth/me")).body;
      const project = (await api("POST", "/projects", { key: ${JSON.stringify(KEY)}, name: "Time log proof" })).body;
      const off = (await api("POST", "/projects", { key: ${JSON.stringify(KEY + "X")}, name: "Time log proof (logging off)" })).body;
      const unloggable = (await api("POST", "/items", { project_id: off.id, title: "cannot take time", assignee_id: me.id })).body;
      await api("PUT", "/projects/" + project.id + "/timelogging", { enabled: true });
      const item = async (title) => (await api("POST", "/items", { project_id: project.id, title, assignee_id: me.id })).body;
      const a = await item("render farm upgrade");
      const b = await item("review dailies");
      const c = await item("pipeline support");
      // RADD-1572: not assigned to anyone, only commented on by me. The old trays could not show it.
      const touched = (await api("POST", "/items", { project_id: project.id, title: "only commented on" })).body;
      const said = await api("POST", "/items/" + touched.id + "/comments", { body: "looking at this" });
      const categories = (await api("GET", "/work-categories")).body;
      return { me, project, off, unloggable, a, b, c, touched, said: said.status, categories };
    })()`);
    const { project, off, unloggable, a, b, c, touched, categories } = setup;
    projectId = project?.id ?? null;
    offProjectId = off?.id ?? null;
    // RADD-1573: an issue I have nothing to do with — a colleague's, so not even "created by me".
    // Only the tray's search can reach it.
    const colleague = (await session.eval(`(async () => { ${PAGE_API} return (await api("POST", "/users", { email: ${JSON.stringify(COLLEAGUE)}, name: "Time Proof Colleague", password: "change-me-too", instance_role: "admin" })).body; })()`));
    colleagueId = colleague?.id ?? null;
    await session.login(baseUrl, COLLEAGUE, "change-me-too");
    const stranger = await session.eval(`(async () => { ${PAGE_API} return (await api("POST", "/items", { project_id: ${JSON.stringify(project.id)}, title: "zebra crossing audit" })).body; })()`);
    await session.login(baseUrl, email, password);
    check("setup created a project and three assigned issues", Boolean(a?.key && b?.key && c?.key), JSON.stringify({ a: a?.key, b: b?.key, c: c?.key }));

    await session.navigate(`${baseUrl}/timesheet`, 2500);
    const state = async () => {
      const value = await session.eval(STATE);
      for (const day of Object.values(value.days)) for (const card of day.cards) made.add(card.id);
      return value;
    };
    const settled = async (test, label) => {
      let last;
      for (let i = 0; i < 60; i += 1) {
        last = await state();
        if (test(last)) return last;
        await sleep(100);
      }
      context[`timeout: ${label}`] = last;
      return last;
    };
    /** The invariant after every gesture: headers and the week total are sums of the cards. */
    const sums = (value) => {
      const perDay = Object.values(value.days).every((day) => day.header === day.cards.reduce((s, x) => s + x.seconds, 0));
      const total = Object.values(value.days).reduce((s, day) => s + day.header, 0);
      const shown = Object.values(value.days).every((day) => day.cards.every((x) => x.shown === x.seconds));
      return perDay && shown && total === value.week;
    };

    // --- 1. the surface ------------------------------------------------------------------------
    let now = await settled((v) => Object.keys(v.days).length === 7, "seven days");
    const tray = await session.eval(`[...document.querySelectorAll("[data-tray-ticket]")].map((n) => n.dataset.trayTicket)`);
    check("My week is the default surface, with seven day columns for this week", JSON.stringify(Object.keys(now.days)) === JSON.stringify(week), JSON.stringify(Object.keys(now.days)));
    check("the tray offers the issues assigned to me", [a, b, c].every((item) => tray.includes(item.key)), JSON.stringify(tray));

    const why = await session.eval(`Object.fromEntries([...document.querySelectorAll("[data-tray-ticket]")].map((n) => [n.dataset.trayTicket, n.querySelector("[data-ticket-why]")?.textContent ?? ""]))`);
    check("an issue I only commented on is offered, and says that is why (RADD-1572)", /comment/i.test(why[touched.key] ?? ""), JSON.stringify({ said: setup.said, why: why[touched.key] }));
    check("an assigned issue says it is assigned", why[a.key] === "Assigned", JSON.stringify(why[a.key]));

    const blocked = await session.eval(`(() => { const n = document.querySelector("[data-tray-ticket='${unloggable.key}']"); return n ? { draggable: n.draggable, disabled: n.getAttribute("aria-disabled"), title: n.title } : null; })()`);
    check("an issue whose project has time logging off is shown but cannot be dragged, and says why", blocked && blocked.draggable === false && blocked.disabled === "true" && /switched off/.test(blocked.title), JSON.stringify(blocked));

    // --- drag helpers: synthetic HTML5 drag events, as the roadmap proof drives its tray ------
    const drag = (source, day, modifiers = {}) => session.eval(`(() => {
      const from = document.querySelector(${JSON.stringify(source)});
      const to = document.querySelector("[data-day='${day}']");
      if (!from || !to) return { missing: !from ? "source" : "day" };
      const dt = new DataTransfer();
      from.dispatchEvent(new DragEvent("dragstart", { bubbles: true, cancelable: true, dataTransfer: dt }));
      return new Promise((done) => setTimeout(() => {
        const init = { bubbles: true, cancelable: true, dataTransfer: dt, ...${JSON.stringify(modifiers)} };
        const over = new DragEvent("dragover", init);
        to.dispatchEvent(over);
        to.dispatchEvent(new DragEvent("drop", init));
        from.dispatchEvent(new DragEvent("dragend", { bubbles: true, cancelable: true, dataTransfer: dt }));
        done({ accepted: over.defaultPrevented });
      }, 80));
    })()`);

    // --- 2. tray → day logs an hour ------------------------------------------------------------
    const dropped = await drag(`[data-tray-ticket='${a.key}']`, WED);
    now = await settled((v) => v.days[WED].cards.length === 1 && !v.days[WED].cards[0].id.startsWith("tmp"), "tray drop");
    check("a ticket dragged onto Wednesday logs 1h there", dropped.accepted && now.days[WED].cards[0]?.key === a.key && now.days[WED].cards[0].seconds === 3600, JSON.stringify(now.days[WED]));
    check("…and the totals follow (day 1h, week 1h)", sums(now) && now.week === 3600, JSON.stringify({ week: now.week }));
    const stored = await session.eval(`(async () => { ${PAGE_API} return (await api("GET", "/items/${a.id}/timelog")).body.entries.map((e) => [e.worked_on, e.time_spent_seconds]); })()`);
    check("…as a real worklog on the issue", JSON.stringify(stored) === JSON.stringify([[WED, 3600]]), JSON.stringify(stored));
    const cardId = now.days[WED].cards[0]?.id;
    if (!cardId) {
      context.toasts = await session.eval(`[...document.querySelectorAll("[role='status'], [role='alert']")].map((n) => n.textContent.trim())`);
      context.dropped = dropped;
      throw new Error("no card after the tray drop: nothing else can be measured");
    }

    // --- 3. move, then copy ----------------------------------------------------------------------
    await drag(`[data-worklog='${cardId}']`, THU);
    now = await settled((v) => v.days[WED].cards.length === 0 && v.days[THU].cards.length === 1, "move");
    check("dragging the card to Thursday moves it", now.days[THU].cards[0]?.id === cardId && sums(now) && now.week === 3600, JSON.stringify({ wed: now.days[WED], thu: now.days[THU] }));
    await drag(`[data-worklog='${cardId}']`, FRI, { ctrlKey: true });
    now = await settled((v) => v.days[FRI].cards.length === 1 && v.days[THU].cards.length === 1, "copy");
    check("Ctrl-dragging it to Friday copies it (both days hold 1h)", now.days[FRI].cards[0]?.key === a.key && now.days[FRI].cards[0].id !== cardId && sums(now) && now.week === 7200, JSON.stringify({ thu: now.days[THU], fri: now.days[FRI] }));

    // --- 4. resize by the bottom edge: real pointer input ---------------------------------------
    const edge = await session.eval(`(() => { const r = document.querySelector("[data-worklog='${cardId}'] [data-resize]").getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
    await session.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: edge.x, y: edge.y });
    await session.send("Input.dispatchMouseEvent", { type: "mousePressed", x: edge.x, y: edge.y, button: "left", clickCount: 1 });
    for (const step of [0.4, 0.8, 1.0]) {
      await session.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: edge.x, y: edge.y + HOUR_PX * step, button: "left", buttons: 1 });
      await sleep(40);
    }
    await session.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: edge.x, y: edge.y + HOUR_PX, button: "left", clickCount: 1 });
    now = await settled((v) => v.days[THU].cards[0]?.seconds === 7200, "resize");
    check("pulling the bottom edge down one hour makes it 2h", now.days[THU].cards[0]?.seconds === 7200 && sums(now), JSON.stringify(now.days[THU]));
    check("…and the card grew with it", now.days[THU].cards[0]?.height >= 2 * HOUR_PX, `height ${now.days[THU].cards[0]?.height}px`);

    // --- 5. type a duration, then a note --------------------------------------------------------
    const dbl = (selector) => session.eval(`(() => { const n = document.querySelector(${JSON.stringify(selector)}); n.dispatchEvent(new MouseEvent("dblclick", { bubbles: true })); return true; })()`);
    const typeInto = async (selector, text) => {
      await session.eval(`(() => { const n = document.querySelector(${JSON.stringify(selector)}); n.focus(); n.select(); return true; })()`);
      await session.send("Input.insertText", { text });
      await session.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
      await session.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
    };
    await dbl(`[data-worklog='${cardId}'] [data-duration]`);
    await sleep(150);
    await typeInto(`[data-worklog='${cardId}'] [data-duration-input]`, "45m");
    now = await settled((v) => v.days[THU].cards[0]?.seconds === 2700, "typed duration");
    check("double-clicking the duration and typing 45m sets it", now.days[THU].cards[0]?.seconds === 2700 && sums(now), JSON.stringify(now.days[THU]));
    await dbl(`[data-worklog='${cardId}'] [data-card-body]`);
    await sleep(150);
    await typeInto(`[data-worklog='${cardId}'] [data-note-input]`, "sync with lighting");
    await sleep(600);
    const note = await session.eval(`(async () => { ${PAGE_API} return (await api("GET", "/items/${a.id}/timelog")).body.entries.find((e) => e.id === "${cardId}")?.note; })()`);
    const noteShown = await session.eval(`document.querySelector("[data-worklog='${cardId}']")?.textContent.includes("sync with lighting")`);
    check("double-clicking the card and typing sets the note, on the card and on the worklog", note === "sync with lighting" && noteShown, JSON.stringify({ note, noteShown }));

    // --- 6. the keyboard -------------------------------------------------------------------------
    const key = async (selector, name, code, vk, text) => {
      await session.eval(`document.querySelector(${JSON.stringify(selector)}).focus()`);
      await session.send("Input.dispatchKeyEvent", { type: "keyDown", key: name, code, windowsVirtualKeyCode: vk, text });
      await session.send("Input.dispatchKeyEvent", { type: "keyUp", key: name, code, windowsVirtualKeyCode: vk });
    };
    await key(`[data-worklog='${cardId}']`, "+", "Equal", 187, "+");
    now = await settled((v) => v.days[THU].cards[0]?.seconds === 3600, "plus key");
    check("+ on a focused card adds 15 minutes", now.days[THU].cards[0]?.seconds === 3600 && sums(now), JSON.stringify(now.days[THU]));
    const copyId = now.days[FRI].cards[0].id;
    await key(`[data-worklog='${copyId}']`, "Delete", "Delete", 46);
    now = await settled((v) => v.days[FRI].cards.length === 0, "delete key");
    check("Delete on a focused card removes it", now.days[FRI].cards.length === 0 && sums(now) && now.week === 3600, JSON.stringify(now.days[FRI]));

    // --- 7. general time -------------------------------------------------------------------------
    const category = categories?.[0];
    if (category) {
      await drag(`[data-tray-category=${JSON.stringify(category.name)}]`, MON);
      now = await settled((v) => v.days[MON].cards.length === 1, "category drop");
      check("a category chip dragged onto Monday logs 1h with no issue", now.days[MON].cards[0]?.key === category.name && now.days[MON].cards[0].seconds === 3600 && sums(now), JSON.stringify(now.days[MON]));
    } else {
      check("a work category exists to log general time against", false, "no categories on this instance");
    }

    // --- 8. the Add row: no drag at all ---------------------------------------------------------
    await session.eval(`document.querySelector("[data-day='${TUE}'] [data-add]").click()`);
    await sleep(150);
    await session.eval(`document.querySelector("[data-day='${TUE}'] [data-add-row] input").focus()`);
    await session.send("Input.insertText", { text: "review dailies" });
    let hit = null;
    for (let i = 0; i < 80 && !hit; i += 1) {
      await sleep(150);
      hit = await session.eval(`document.querySelector("[data-day='${TUE}'] [data-add-hit='${b.key}']") ? true : null`);
    }
    if (hit) await session.eval(`document.querySelector("[data-day='${TUE}'] [data-add-hit='${b.key}']").click()`);
    now = await settled((v) => v.days[TUE].cards.length === 1, "add row");
    check("the Add row finds an issue by its words and logs 1h on that day", Boolean(hit) && now.days[TUE].cards[0]?.key === b.key && sums(now), JSON.stringify({ hit, tue: now.days[TUE] }));

    // --- 8b. type a duration beside a ticket (RADD-1573) -----------------------------------------
    const OTHER = week.find((day) => day !== TODAY && day !== MON && day !== TUE && day !== WED && day !== THU && day !== FRI) ?? week.find((day) => day !== TODAY);
    const targetOf = () => session.eval(`({ day: document.querySelector("[data-day-target]")?.dataset.day ?? null, label: document.querySelector("[data-log-target-label]")?.textContent ?? "" })`);
    const on = (value, day, key, seconds) => value.days[day].cards.filter((card) => card.key === key && card.seconds === seconds).length;
    let target = await targetOf();
    check("typed time goes on today unless another day is picked, and the tray says so", target.day === TODAY && /today/.test(target.label), JSON.stringify(target));
    const beforeToday = on(now, TODAY, c.key, 5400);
    await typeInto(`[data-quick-log='${c.key}']`, "1.5");
    now = await settled((v) => on(v, TODAY, c.key, 5400) === beforeToday + 1, "quick log today");
    check("typing 1.5 beside a ticket and pressing Enter logs 1h 30m on it today", on(now, TODAY, c.key, 5400) === beforeToday + 1 && sums(now), JSON.stringify(now.days[TODAY]));
    const logged = await session.eval(`document.querySelector("[data-tray-row='${c.key}'] [data-ticket-why]")?.textContent ?? ""`);
    let seen = logged;
    for (let i = 0; i < 40 && !/1h 30m/.test(seen); i += 1) { await sleep(150); seen = await session.eval(`document.querySelector("[data-tray-row='${c.key}'] [data-ticket-why]")?.textContent ?? ""`); }
    check("…and the ticket's own figure follows", /1h 30m/.test(seen), seen);

    await session.eval(`document.querySelector("[data-day='${OTHER}'] [data-day-pick]").click()`);
    await sleep(150);
    target = await targetOf();
    check("clicking another day's name makes it the day typed time goes on", target.day === OTHER && !/today/.test(target.label), JSON.stringify(target));
    const beforeOther = now.days[OTHER].cards.length;
    await typeInto(`[data-quick-log='${a.key}']`, "30m");
    now = await settled((v) => v.days[OTHER].cards.length === beforeOther + 1, "quick log other day");
    check("…and 30m typed beside a ticket lands there", on(now, OTHER, a.key, 1800) === 1 && sums(now), JSON.stringify(now.days[OTHER]));

    const cardsBefore = Object.values(now.days).reduce((sum, day) => sum + day.cards.length, 0);
    await typeInto(`[data-quick-log='${b.key}']`, "soon");
    await sleep(600);
    const refused = await session.eval(`(() => { const n = document.querySelector("[data-quick-log='${b.key}']"); return { invalid: n.getAttribute("aria-invalid"), value: n.value }; })()`);
    now = await state();
    check("something that is not a duration is marked and logs nothing", refused.invalid === "true" && refused.value === "soon" && Object.values(now.days).reduce((sum, day) => sum + day.cards.length, 0) === cardsBefore, JSON.stringify(refused));

    const listedBefore = await session.eval(`Boolean(document.querySelector("[data-tray-row='${stranger.key}']"))`);
    await session.eval(`document.querySelector("[data-ticket-filter]").focus()`);
    await session.send("Input.insertText", { text: "zebra crossing" });
    let foundRow = false;
    for (let i = 0; i < 80 && !foundRow; i += 1) { await sleep(150); foundRow = await session.eval(`Boolean(document.querySelector("[data-ticket-found] [data-tray-row='${stranger.key}']"))`); }
    check("an issue I have nothing to do with is not on my list, and the same box finds it", !listedBefore && foundRow, JSON.stringify({ listedBefore, foundRow, key: stranger.key }));
    if (foundRow) {
      await typeInto(`[data-quick-log='${stranger.key}']`, "1:15");
      now = await settled((v) => on(v, OTHER, stranger.key, 4500) === 1, "quick log found");
      check("…and 1:15 typed beside it logs 1h 15m", on(now, OTHER, stranger.key, 4500) === 1 && sums(now), JSON.stringify(now.days[OTHER]));
    }
    await session.eval(`(() => { const n = document.querySelector("[data-ticket-filter]"); n.focus(); n.select(); return true; })()`);
    await session.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Backspace", code: "Backspace", windowsVirtualKeyCode: 8 });
    await session.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Backspace", code: "Backspace", windowsVirtualKeyCode: 8 });
    await sleep(300);

    // --- 9/11. totals and layout ----------------------------------------------------------------
    context.final = now;
    check("the week total is the sum of every card on screen", sums(now) && now.week === 3 * 3600 + 5400 + 1800 + 4500, `week ${now.week / 3600}h`);
    const layout = await session.eval(`(() => {
      const columns = [...document.querySelectorAll("[data-day]")].map((n) => Math.round(n.getBoundingClientRect().width));
      const sizes = [...document.querySelectorAll("[data-timelog-calendar] *")].filter((n) => n.children.length === 0 && n.textContent.trim()).map((n) => parseFloat(getComputedStyle(n).fontSize));
      return { columns, minFont: Math.min(...sizes), overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth };
    })()`);
    context.layout = layout;
    check("seven columns of at least 150px with no horizontal page scroll at 1440px", layout.columns.length === 7 && Math.min(...layout.columns) >= 150 && layout.overflow <= 0, JSON.stringify(layout));
    check("no text on the surface is under the type scale's meta step (12px)", layout.minFont >= 12, `smallest ${layout.minFont}px`);
    await session.screenshot(outputPath("timelog-calendar-proof.png"));

    // --- 10. the report agrees --------------------------------------------------------------------
    await session.eval(`document.querySelector("[data-timesheet-mode='report']").click()`);
    let reported = false;
    for (let i = 0; i < 60 && !reported; i += 1) {
      await sleep(150);
      reported = await session.eval(`document.body.textContent.includes(${JSON.stringify(a.key)}) && document.body.textContent.includes(${JSON.stringify(b.key)}) && !document.querySelector("[data-timelog-calendar]")`);
    }
    check("the Report tab shows the same entries", reported);
    const reloaded = await session.eval(`location.search`);
    check("…and which tab is open lives in the URL", String(reloaded).includes("m=report"), String(reloaded));
  } catch (error) {
    check("the proof ran to its end", false, String(error?.message ?? error));
  } finally {
    await session.eval(`(async () => { ${PAGE_API}
      for (const id of ${JSON.stringify([...made])}) await api("DELETE", "/worklogs/" + id);
      ${projectId ? `await api("DELETE", "/projects/${projectId}");` : ""}
      ${offProjectId ? `await api("DELETE", "/projects/${offProjectId}");` : ""}
      ${colleagueId ? `await api("DELETE", "/users/${colleagueId}");` : ""}
      return true;
    })()`).catch(() => null);
    await close();
  }
  finish(context);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

#!/usr/bin/env node
/**
 * RADD-1575 proof — logging time from My Work, in a real browser against a real backend.
 *
 *   1. My Work offers a "Log time" widget to someone the Timesheet is offered to
 *   2. it lists an issue assigned to me, with a duration field
 *   3. typing 45m and pressing Enter logs a real 45m worklog on it, dated today
 *   4. the widget's "Today" total and the ticket's own figure follow
 *   5. the widget fits its card: nothing scrolls sideways, text at the type scale's meta step or more
 *
 *   node web/scripts/log-time-widget-proof.mjs http://127.0.0.1:8000 admin@example.com change-me
 *
 * Creates a project with one issue and deletes it.
 */
import { resolve } from "node:path";
import { outputPath, PAGE_API, sleep } from "./lib/cdp.mjs";
import { startProof } from "./lib/proof.mjs";

const PORT = 9499;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-logtime-widget-proof");
const KEY = `LW${Date.now().toString(36).slice(-4).toUpperCase()}`;
const seconds = (text) => { let s = 0; for (const [, n, u] of text.matchAll(/(\d+)(h|m)/g)) s += Number(n) * (u === "h" ? 3600 : 60); return s; };

async function main() {
  const { session, close, baseUrl, finish, check } = await startProof({ port: PORT, profile: PROFILE, width: 1440, height: 1000 });
  const context = { key: KEY };
  let projectId = null;
  try {
    const setup = await session.eval(`(async () => { ${PAGE_API}
      const me = (await api("GET", "/auth/me")).body;
      const project = (await api("POST", "/projects", { key: ${JSON.stringify(KEY)}, name: "Log time widget proof" })).body;
      await api("PUT", "/projects/" + project.id + "/timelogging", { enabled: true });
      const item = (await api("POST", "/items", { project_id: project.id, title: "grade the trailer", assignee_id: me.id })).body;
      return { project, item };
    })()`);
    projectId = setup.project?.id ?? null;
    const { item } = setup;

    await session.navigate(`${baseUrl}/`, 2500);
    let present = false;
    for (let i = 0; i < 60 && !present; i += 1) { await sleep(150); present = await session.eval(`Boolean(document.querySelector("[data-log-time-widget] [data-quick-log='${item.key}']"))`); }
    check("My Work has a Log time widget listing the issue assigned to me, with a duration field", present);
    if (!present) throw new Error("no widget: nothing else can be measured");

    const READ = `(() => { const w = document.querySelector("[data-log-time-widget]"); return {
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
    await session.screenshot(outputPath("log-time-widget-proof.png"));
  } finally {
    if (projectId) await session.eval(`(async () => { ${PAGE_API} await api("DELETE", "/projects/${projectId}"); return true; })()`).catch(() => null);
    await close();
  }
  finish(context);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

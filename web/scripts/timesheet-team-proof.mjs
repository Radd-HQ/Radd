#!/usr/bin/env node
/**
 * RADD-1574 proof — the timesheet's Team tab, in a real browser against a real backend.
 *
 * Four people in one team, last week (a complete one):
 *   - Bulk   booked the whole week, 40h, on Friday
 *   - Silent logged nothing
 *   - Steady logged 8h a day
 *   - Away   logged 8h Monday to Wednesday and was on leave Thursday and Friday
 *
 *   1. /timesheet has a Team tab for someone who may see others' time
 *   2. it lists all four — Silent included, who has no time at all
 *   3. Bulk is flagged for booking the week on one day AND for a 40h day, with the figures in words
 *   4. Silent is flagged for nothing logged
 *   5. Steady and Away are not flagged; Away's leave lowered what was expected of them
 *   6. the people to follow up come first, and the header counts them
 *   7. opening a row shows the days behind it; the report opens filtered to that person
 *   8. the flag text is legible (4.5:1) and nothing scrolls sideways
 *   9. a member who may not see others' time gets no tab and no roster
 *  10. the team's manager, who holds no timesheet.view, gets the tab, their team only, all four
 *      rows with the same flags, and none of an outsider's time (RADD-1576)
 *
 *   node web/scripts/timesheet-team-proof.mjs http://127.0.0.1:8000 admin@example.com change-me
 *
 * Creates a project, a team and four users, and deletes them.
 */
import { resolve } from "node:path";
import { outputPath, PAGE_API, sleep } from "./lib/cdp.mjs";
import { startProof } from "./lib/proof.mjs";

const PORT = 9498;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-team-proof");
const STAMP = Date.now().toString(36);
const KEY = `TT${STAMP.slice(-4).toUpperCase()}`;

/** Last week, Monday to Sunday, in local dates as the page computes them. */
const lastWeek = (() => {
  const now = new Date();
  const monday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - ((now.getDay() + 6) % 7) - 7);
  return Array.from({ length: 7 }, (_, i) => {
    const day = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + i);
    return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
  });
})();
const [MON, TUE, WED, THU, FRI] = lastWeek;

const luminance = (rgb) => {
  const [r, g, b] = rgb.map((v) => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a, b) => { const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); };

async function main() {
  const { session, close, baseUrl, email, password, finish, check } = await startProof({ port: PORT, profile: PROFILE, width: 1440, height: 1000 });
  const context = { key: KEY, lastWeek };
  let made = null;
  try {
    made = await session.eval(`(async () => { ${PAGE_API}
      const project = (await api("POST", "/projects", { key: ${JSON.stringify(KEY)}, name: "Team proof" })).body;
      await api("PUT", "/projects/" + project.id + "/timelogging", { enabled: true });
      const item = (await api("POST", "/items", { project_id: project.id, title: "shot work" })).body;
      const team = (await api("POST", "/teams", { name: ${JSON.stringify(`Team proof ${STAMP}`)} })).body;
      const people = {};
      for (const name of ["Bulk", "Silent", "Steady", "Away"]) {
        const user = (await api("POST", "/users", { email: name.toLowerCase() + "-${STAMP}@example.test", name: name + " ${STAMP}", password: "change-me-too" })).body;
        people[name] = user;
        await api("POST", "/teams/" + team.id + "/members", { user_id: user.id });
      }
      const lead = (await api("POST", "/users", { email: "lead-${STAMP}@example.test", name: "Lead ${STAMP}", password: "change-me-too" })).body;
      const managed = (await api("POST", "/teams/" + team.id + "/managers", { user_id: lead.id })).status;
      const statuses = [];
      const log = async (who, day, time) => statuses.push((await api("POST", "/items/" + item.id + "/worklogs", { time_spent: time, worked_on: day, author_id: people[who].id })).status);
      await log("Bulk", ${JSON.stringify(FRI)}, "40h");
      for (const day of ${JSON.stringify([MON, TUE, WED, THU, FRI])}) await log("Steady", day, "8h");
      for (const day of ${JSON.stringify([MON, TUE, WED])}) await log("Away", day, "8h");
      const leave = await api("POST", "/leave", { user_id: people.Away.id, label: "Holiday", start_date: ${JSON.stringify(THU)}, end_date: ${JSON.stringify(FRI)} });
      // An outsider's hour: the admin is on no team the lead manages.
      const me = (await api("GET", "/auth/me")).body;
      statuses.push((await api("POST", "/items/" + item.id + "/worklogs", { time_spent: "1h", worked_on: ${JSON.stringify(MON)} })).status);
      return { project, team, people, lead, managed, me, statuses, leave: leave.status };
    })()`);
    check("setup: a team of four, their time and two days of leave", made.statuses.every((status) => status === 201) && made.leave === 201, JSON.stringify({ statuses: made.statuses, leave: made.leave }));

    await session.navigate(`${baseUrl}/timesheet`, 2000);
    const tab = await session.eval(`Boolean(document.querySelector("[data-timesheet-mode='team']"))`);
    check("the timesheet offers a Team tab to someone who may see others' time", tab);
    await session.navigate(`${baseUrl}/timesheet?m=team&tm=${made.team.id}&d=${MON}`, 2500);

    const READ = `(() => [...document.querySelectorAll("[data-team-row]")].map((row) => ({
      id: row.dataset.teamRow, name: row.dataset.teamName, flags: row.dataset.teamFlags,
      logged: row.querySelector("[data-team-logged]").textContent, expected: row.querySelector("[data-team-expected]").textContent,
      reasons: [...row.querySelectorAll("[data-team-reasons] li")].map((li) => li.textContent),
    })))()`;
    let rows = [];
    for (let i = 0; i < 80; i += 1) {
      rows = await session.eval(READ);
      // Leave arrives from the plugin's own data source a moment after the sheet.
      if (rows.length === 4 && rows.find((row) => row.name.startsWith("Away"))?.expected === "24h") break;
      await sleep(150);
    }
    context.rows = rows;
    const of = (name) => rows.find((row) => row.name.startsWith(name)) ?? {};
    check("all four people are listed, the one with no time included", rows.length === 4 && Boolean(of("Silent").id), JSON.stringify(rows.map((row) => row.name)));
    check("a week booked on one day is flagged for too few days and for the day itself", of("Bulk").flags === "few_days,long_day", of("Bulk").flags);
    check("…with the figures in words", /Time on 1 of 5 working days; 40h of it on /.test(of("Bulk").reasons?.[0] ?? "") && /1 day over 10h: .*\(40h\)/.test(of("Bulk").reasons?.[1] ?? ""), JSON.stringify(of("Bulk").reasons));
    check("…although the total is exactly what was expected", of("Bulk").logged === "40h" && of("Bulk").expected === "40h", JSON.stringify(of("Bulk")));
    check("nothing logged is flagged as that", of("Silent").flags === "nothing" && of("Silent").reasons?.[0] === "Nothing logged in 5 working days", JSON.stringify(of("Silent")));
    check("eight hours a day is not flagged", of("Steady").flags === "" && of("Steady").logged === "40h", JSON.stringify(of("Steady")));
    check("two days of leave lower what is expected (24h), and the short week is not flagged", of("Away").expected === "24h" && of("Away").logged === "24h" && of("Away").flags === "", JSON.stringify(of("Away")));
    const order = rows.map((row) => Boolean(row.flags));
    check("people to follow up are listed first", JSON.stringify(order) === JSON.stringify([true, true, false, false]), JSON.stringify(rows.map((row) => `${row.name.split(" ")[0]}:${row.flags}`)));
    const summary = await session.eval(`document.querySelector("[data-team-summary]")?.textContent ?? ""`);
    check("the header counts them", /2 of 4 to follow up/.test(summary), summary);

    // 7 — the days behind a row
    await session.eval(`document.querySelector("[data-team-row='${of("Bulk").id}'] button").click()`);
    await sleep(300);
    const days = await session.eval(`Object.fromEntries([...document.querySelectorAll("[data-team-detail='${of("Bulk").id}'] [data-team-day]")].map((n) => [n.dataset.teamDay, n.lastElementChild.textContent]))`);
    check("opening a row shows each day: nothing Monday to Thursday, 40h on Friday", days[FRI] === "40h" && days[MON] === "·" && Object.keys(days).length === 7, JSON.stringify(days));
    await session.eval(`document.querySelector("[data-team-row='${of("Away").id}'] button").click()`);
    await sleep(300);
    const away = await session.eval(`Object.fromEntries([...document.querySelectorAll("[data-team-detail='${of("Away").id}'] [data-team-day]")].map((n) => [n.dataset.teamDay, n.lastElementChild.textContent]))`);
    check("a day of leave reads as off, not as a gap", away[THU] === "off" && away[FRI] === "off" && away[MON] === "8h", JSON.stringify(away));

    // 8 — legibility and layout
    const ink = await session.eval(`(() => {
      const li = document.querySelector("[data-team-reasons] li span");
      const rgb = (value) => value.match(/\\d+(\\.\\d+)?/g).slice(0, 3).map(Number);
      let node = li, background = null;
      while (node && !background) { const bg = getComputedStyle(node).backgroundColor; if (!/rgba\\(0, 0, 0, 0\\)|transparent/.test(bg)) background = bg; node = node.parentElement; }
      return { text: rgb(getComputedStyle(li).color), background: rgb(background ?? "rgb(0,0,0)"), size: parseFloat(getComputedStyle(li).fontSize),
               overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth };
    })()`);
    const ratio = contrast(ink.text, ink.background);
    check("the reason text is at least 4.5:1 on its background", ratio >= 4.5, `${ratio.toFixed(2)}:1 at ${ink.size}px`);
    check("nothing scrolls sideways at 1440px", ink.overflow <= 0, `overflow ${ink.overflow}px`);
    await session.screenshot(outputPath("timesheet-team-proof.png"));

    await session.eval(`document.querySelector("[data-team-detail='${of("Away").id}'] [data-team-open-report]").click()`);
    await sleep(1500);
    const report = await session.eval(`({ selected: document.querySelector("[data-timesheet-mode='report']")?.getAttribute("aria-selected"), search: location.search, text: document.body.innerText })`);
    check("the report opens filtered to that person", report.selected === "true" && report.search.includes(of("Away").id) && report.text.includes("Away") && !report.text.includes(`Steady ${STAMP}`), JSON.stringify({ selected: report.selected, search: report.search }));

    // 9 — someone who may NOT see others' time: no tab, and the roster is not theirs to read
    await session.login(baseUrl, `steady-${STAMP}@example.test`, "change-me-too");
    await session.navigate(`${baseUrl}/timesheet?m=team&tm=${made.team.id}&d=${MON}`, 2000);
    const member = await session.eval(`(async () => { ${PAGE_API}
      const sheet = (await api("GET", "/timesheet?start=${MON}&end=${FRI}&team_id=${made.team.id}")).body;
      return { tab: Boolean(document.querySelector("[data-timesheet-mode='team']")), screen: Boolean(document.querySelector("[data-team-report]")),
               people: (sheet.people ?? []).map((p) => p.name), authors: [...new Set((sheet.entries ?? []).map((e) => e.user.name))] };
    })()`);
    check("a member without timesheet.view gets no Team tab, and the sheet names only them", !member.tab && !member.screen && member.people.length === 1 && member.people[0].startsWith("Steady") && member.authors.length <= 1, JSON.stringify(member));

    // 10 — the team's manager: no global permission, their own team
    check("setup: the lead manages the team", made.managed === 204 || made.managed === 201 || made.managed === 200, String(made.managed));
    await session.login(baseUrl, `lead-${STAMP}@example.test`, "change-me-too");
    await session.navigate(`${baseUrl}/timesheet?m=team&d=${MON}`, 2500);
    let led = [];
    for (let i = 0; i < 80; i += 1) {
      led = await session.eval(READ);
      if (led.length === 4 && led.find((row) => row.name.startsWith("Away"))?.expected === "24h") break;
      await sleep(150);
    }
    const lead = await session.eval(`(async () => { ${PAGE_API}
      const me = (await api("GET", "/auth/me")).body;
      const teams = (await api("GET", "/timesheet/teams")).body;
      const outsider = (await api("GET", "/timesheet?start=${MON}&end=${FRI}&user_id=${made.me.id}")).body;
      const unasked = (await api("GET", "/timesheet?start=${MON}&end=${FRI}")).body;
      return { view: (me.permissions ?? []).includes("timesheet.view") || (me.permissions ?? []).includes("*"),
               tab: Boolean(document.querySelector("[data-timesheet-mode='team']")), teams: teams.map((team) => team.id),
               picker: document.querySelector("[data-team-report] [aria-label='Team']")?.textContent ?? "",
               outsider: (outsider.entries ?? []).length, unasked: [...new Set((unasked.entries ?? []).map((e) => e.user.name))] };
    })()`);
    context.lead = { lead, led };
    const ledOf = (name) => led.find((row) => row.name.startsWith(name)) ?? {};
    check("the lead holds no timesheet.view", lead.view === false, JSON.stringify(lead.view));
    check("the lead gets the Team tab and is offered their own team, and only it", lead.tab && lead.teams.length === 1 && lead.teams[0] === made.team.id && lead.picker.includes("Team proof"), JSON.stringify({ tab: lead.tab, teams: lead.teams, picker: lead.picker }));
    check("the lead sees all four members with the same flags", led.length === 4 && ledOf("Bulk").flags === "few_days,long_day" && ledOf("Silent").flags === "nothing" && ledOf("Steady").logged === "40h", JSON.stringify(led.map((row) => `${row.name.split(" ")[0]}:${row.logged}:${row.flags}`)));
    check("the lead gets none of an outsider's time, and an unfiltered sheet stays their own", lead.outsider === 0 && lead.unasked.length === 0, JSON.stringify({ outsider: lead.outsider, unasked: lead.unasked }));
    await session.login(baseUrl, email, password);
    const admin = await session.eval(`(async () => { ${PAGE_API} return ((await api("GET", "/timesheet?start=${MON}&end=${FRI}&user_id=${made.me.id}")).body.entries ?? []).length; })()`);
    check("…which is there: the admin reads it", admin >= 1, String(admin));
  } finally {
    if (made) {
      await session.eval(`(async () => { ${PAGE_API}
        await api("DELETE", "/projects/${made.project.id}");
        await api("DELETE", "/teams/${made.team.id}");
        for (const id of ${JSON.stringify([...Object.values(made.people), made.lead].map((person) => person.id))}) await api("DELETE", "/users/" + id);
        return true;
      })()`).catch(() => null);
    }
    await close();
  }
  finish(context);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

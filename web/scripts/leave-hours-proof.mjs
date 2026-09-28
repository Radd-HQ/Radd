/** RADD-1481, against a real backend: leave with hours (timed, mixed, all-day) from the profile form,
 *  a steward recording a member's leave from the Team leave section, the member seeing it and being
 *  refused the team view, the away indicator honouring the start hour, and the timesheet's boundary
 *  cells naming the hours. Creates a team, four leave rows and one worklog, and removes them all.
 *
 *    node web/scripts/leave-hours-proof.mjs [baseUrl] [adminEmail] [adminPassword]
 *  Steward/member accounts: RADD_PROOF_STEWARD / RADD_PROOF_MEMBER as email:password
 *  (defaults: the dev stack's proof-member / clean-member accounts; the member holds no grants). */
import { mkdtemp } from "node:fs/promises";
import { startProof } from "./lib/proof.mjs";
import { PAGE_API, outputPath, until } from "./lib/cdp.mjs";

const [stewardEmail, stewardPassword] = (process.env.RADD_PROOF_STEWARD ?? "proof-member@example.test:proof-member-1").split(":");
const [memberEmail, memberPassword] = (process.env.RADD_PROOF_MEMBER ?? "clean-member@example.test:clean-member-1").split(":");
const TEAM = `Leave proof ${Math.random().toString(16).slice(2, 8)}`;
const MARK = "leave-hours proof";
const TL = 'section[aria-label="Team leave"]';
const L = 'section[aria-label="Leave"]';

const proof = await startProof({ port: 18829, profile: await mkdtemp("/tmp/radd-leave-hours-"), scale: 1 });
const { session: s, baseUrl, check } = proof;
const api = (method, path, body) => s.eval(`(async()=>{${PAGE_API} return api(${JSON.stringify(method)}, ${JSON.stringify(path)}${body === undefined ? "" : `, ${JSON.stringify(body)}`});})()`);
const login = async (email, password) => { const status = await s.login(baseUrl, email, password); if (status !== 204 && status !== 200) throw new Error(`login ${email} → ${status}`); };
const text = (selector) => s.eval(`document.querySelector(${JSON.stringify(selector)})?.innerText ?? null`);
// React-controlled inputs take a value through the native setter plus an input event.
const SET = `const setInput=(el,v)=>{Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el),'value').set.call(el,v);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));};
const selectByOption=(root,first,value)=>{const sel=[...root.querySelectorAll('select')].find(x=>x.options[0]?.text===first);setInput(sel,value);};`;
const fillForm = (root, { from, fromTime, to, toTime, allDay }) => s.eval(`(()=>{${SET}
  const root=document.querySelector(${JSON.stringify(root)}); const form=root.querySelector('form');
  const sw=root.querySelector('[data-testid="leave-all-day"]'); if(sw && (sw.getAttribute('aria-checked')==='true')!==${allDay}) sw.click();
  return new Promise(r=>setTimeout(r,50)).then(()=>{
    setInput(form.querySelector('input:not([type=date]):not([type=time])'), ${JSON.stringify(MARK)});
    const dates=form.querySelectorAll('input[type=date]'); setInput(dates[0],${JSON.stringify(from)}); setInput(dates[1],${JSON.stringify(to)});
    const times=form.querySelectorAll('input[type=time]');
    if(times.length){ setInput(times[0],${JSON.stringify(fromTime ?? "")}); setInput(times[1],${JSON.stringify(toTime ?? "")}); }
    return {times:times.length, disabled: form.querySelector('button[type=submit]').disabled};
  });})()`);
const submit = (root) => s.eval(`document.querySelector(${JSON.stringify(root)} + ' form button[type=submit]').click()`);
const rowCount = (root) => s.eval(`document.querySelectorAll(${JSON.stringify(root)} + ' li').length`);
const hasRow = (root, needle) => s.eval(`[...document.querySelectorAll(${JSON.stringify(root)} + ' li')].some(li=>li.innerText.includes(${JSON.stringify(needle)}))`);
const addRow = async (root, span, label) => {
  const before = await rowCount(root);
  const shape = await fillForm(root, span);
  await submit(root);
  await until(s, async () => (await rowCount(root)) === before + 1, `${label} row appears`);
  return shape;
};

let teamId, worklogId, memberId, stewardId;
try {
  // --- actors and fixtures -------------------------------------------------------------------
  await login(memberEmail, memberPassword);
  const member = (await api("GET", "/auth/me")).body; memberId = member.id;
  await login(stewardEmail, stewardPassword);
  stewardId = (await api("GET", "/auth/me")).body.id;
  // A timesheet row is one person's logged time: the steward logs an hour in the proof week.
  const categories = (await api("GET", "/work-categories")).body;
  const category = (Array.isArray(categories) ? categories : categories?.items ?? [])[0];
  const worklog = await api("POST", "/worklogs", { time_spent: "1h", worked_on: "2026-09-30", note: MARK, category_id: category?.id });
  check("steward logs an hour on Sep 30 (a timesheet row to hang the leave cells on)", worklog.status === 201, `→ ${worklog.status}`);
  worklogId = worklog.body?.id;
  await login(proof.email, proof.password);
  const team = await api("POST", "/teams", { name: TEAM, owner_id: stewardId });
  check("admin creates a team owned by the steward", team.status === 201, `→ ${team.status}`);
  teamId = team.body.id;
  const added = await api("POST", `/teams/${teamId}/members`, { user_id: memberId });
  check("member joins the team", added.status === 201, `→ ${added.status}`);
  const timedHoliday = await api("POST", "/leave", { team_id: teamId, label: "Eve", start_date: "2026-12-24", end_date: "2026-12-24", start_time: "13:00" });
  check("a holiday with a time is refused (409)", timedHoliday.status === 409, `→ ${timedHoliday.status} ${JSON.stringify(timedHoliday.body).slice(0, 80)}`);

  // --- the steward's profile: Team leave -----------------------------------------------------
  await login(stewardEmail, stewardPassword);
  await s.navigate(`${baseUrl}/settings/profile`);
  await until(s, () => s.eval(`document.querySelector('${TL}') !== null && document.querySelector('${L} form') !== null`), "profile shows Leave and Team leave");
  check("steward's profile shows the Team leave section", true);
  await s.eval(`(()=>{${SET} const root=document.querySelector('${TL}'); const sel=[...root.querySelectorAll('select')].find(x=>x.options[0]?.text!=='Select member…'); if(sel) setInput(sel,${JSON.stringify(teamId)});})()`);
  await until(s, () => s.eval(`[...document.querySelectorAll('${TL} select')].some(x=>x.options[0]?.text==='Select member…' && [...x.options].some(o=>o.value===${JSON.stringify(memberId)}))`), "team's members loaded");
  await s.eval(`(()=>{${SET} selectByOption(document.querySelector('${TL}'),'Select member…',${JSON.stringify(memberId)});})()`);
  const timed = await addRow(TL, { from: "2026-09-30", fromTime: "12:00", to: "2026-10-03", toTime: "16:00", allDay: false }, "team leave");
  check("All day off reveals two time fields", timed.times === 2, JSON.stringify(timed));
  check("team list shows the member's timed span", await hasRow(TL, "Sep 30, 12:00 – Oct 3, 16:00") && await hasRow(TL, member.name), await text(`${TL} ul`));
  await s.eval(`document.querySelector('${L}').scrollIntoView({block:"start"})`);
  await s.screenshot(outputPath("leave-hours-team.png"));

  // --- the steward's own leave: timed, mixed (from an hour ago, through tomorrow), all-day ----
  const clock = await s.eval(`(()=>{const day=d=>new Intl.DateTimeFormat('en-CA',{year:'numeric',month:'2-digit',day:'2-digit'}).format(d); const at=new Date(Date.now()-3600e3); return {day:day(new Date()), hm: at.getHours()<1?'00:00':at.toTimeString().slice(0,5), tomorrow:day(new Date(Date.now()+86400e3))};})()`);
  await addRow(L, { from: "2026-10-01", fromTime: "09:00", to: "2026-10-02", toTime: "13:00", allDay: false }, "own timed leave");
  check("own list shows the timed span", await hasRow(L, "Oct 1, 09:00 – Oct 2, 13:00"), await text(`${L} ul`));
  await addRow(L, { from: clock.day, fromTime: clock.hm, to: clock.tomorrow, toTime: "", allDay: false }, "mixed leave");
  check("own list shows the mixed span (start hour, whole next day)", await hasRow(L, `${clock.hm} – `), await text(`${L} ul`));
  await addRow(L, { from: "2026-10-06", to: "2026-10-07", allDay: true }, "all-day leave");
  check("own list shows the all-day span without times", await hasRow(L, "Oct 6 – Oct 7"), await text(`${L} ul`));
  const current = (await api("GET", "/leave/current")).body;
  const ids = new Set(current.map((row) => row.user_id));
  check("away NOW: the steward (started an hour ago), not the member (starts Sep 30)", ids.has(stewardId) && !ids.has(memberId), JSON.stringify(current.filter((r) => r.user_id === stewardId || r.user_id === memberId)));
  await until(s, () => s.eval(`document.querySelectorAll('[aria-label="On leave"]').length > 0`), "away indicator on the steward's own avatar");
  check("the away indicator appears without a reload", true);

  // --- the member: sees it under My leave, gets no Team leave, is refused the team view --------
  await login(memberEmail, memberPassword);
  await s.navigate(`${baseUrl}/settings/profile`);
  await until(s, () => s.eval(`document.querySelector('${L} form') !== null`), "member profile ready");
  check("member sees the steward-recorded span under Leave", await hasRow(L, "Sep 30, 12:00 – Oct 3, 16:00"), await text(`${L} ul`));
  check("member has no Team leave section", (await s.eval(`document.querySelector('${TL}')`)) === null);
  const refused = await api("GET", `/leave/teams/${teamId}`);
  check("member is refused the team's leave (403)", refused.status === 403, `→ ${refused.status}`);
  const mine = (await api("GET", "/leave/mine")).body.find((row) => row.start_date === "2026-09-30");
  check("the row carries its times and a zone", mine?.start_time === "12:00:00" && mine?.end_time === "16:00:00" && Boolean(mine?.timezone), JSON.stringify(mine));

  // --- the timesheet: the steward's boundary cells name the hours ----------------------------
  await login(proof.email, proof.password);
  await s.navigate(`${baseUrl}/timesheet?g=person&d=2026-09-30`, 3000);
  await until(s, () => s.eval(`document.querySelector('td[title*="from 09:00"]') !== null`), "timesheet shows the start cell");
  const cells = await s.eval(`[...document.querySelectorAll('td[title*="Leave"]')].map(td=>td.title)`);
  check("Oct 1 says from 09:00, Oct 2 says until 13:00, today says from the mixed start", cells.some((t) => t.includes("from 09:00")) && cells.some((t) => t.includes("until 13:00")) && cells.some((t) => t.includes(`from ${clock.hm}`)), JSON.stringify(cells));
  const chip = await s.eval(`(()=>{const td=document.querySelector('td[title*="from 09:00"]'); const chip=td?.querySelector('[aria-label="On leave"]'); if(!chip) return null; const r=chip.getBoundingClientRect(); return {w:r.width,h:r.height,text:chip.textContent};})()`);
  check("the boundary cell renders the away chip with size", chip && chip.w > 10 && chip.h > 8, JSON.stringify(chip));
  await s.eval(`document.querySelector('td[title*="from 09:00"]')?.scrollIntoView({block:"center"})`);
  await s.screenshot(outputPath("leave-hours-timesheet.png"));
} catch (error) {
  check("the proof ran to completion", false, String(error).split("\n").slice(0, 2).join(" | "));
} finally {
  // --- teardown ---------------------------------------------------------------------------------
  try {
    await login(proof.email, proof.password);
    for (const id of [memberId, stewardId].filter(Boolean)) {
      for (const row of (await api("GET", `/leave/users/${id}`)).body ?? []) if (row.label === MARK) await api("DELETE", `/leave/${row.id}`);
    }
    if (teamId) await api("DELETE", `/teams/${teamId}`);
    if (worklogId) { await login(stewardEmail, stewardPassword); await api("DELETE", `/worklogs/${worklogId}`); }
  } catch (error) { console.error("teardown:", error); }
  await proof.close();
  proof.finish({ team: TEAM });
}

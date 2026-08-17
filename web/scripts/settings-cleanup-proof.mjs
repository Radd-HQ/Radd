/**
 * RADD-927: the settings cleanup wave, in the running UI.
 *
 * Four claims a clean `tsc` cannot make. Each was a real symptom on the live
 * instance, and each is fixed by a mechanism rather than by moving one thing:
 *
 *   1. A settings tab owned by an optional plugin DISAPPEARS when that plugin
 *      is disabled, and comes back when it is enabled (RADD-928). Proved by
 *      actually disabling Forgejo through the plugin manager and re-reading the
 *      sidebar — the previous behaviour left the tab pointing at an unmounted
 *      router, so every card on the page showed a query error.
 *   2. A cascade setting renders on the surface its owner DECLARED, and project
 *      → General is the REMAINDER rather than a dump (RADD-930).
 *   3. Settings → Time logging holds every instance-scope time answer, and
 *      Holidays / Groups are gone as separate tabs, their paths redirecting
 *      rather than 404ing (RADD-931, RADD-932).
 *   4. A project's Access screen is ONE list of role grants over three subject
 *      kinds, and the Teams panel no longer offers a second way to write the
 *      same row (RADD-929).
 *
 * Run against a dev server with the wave's migration applied.
 */
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const args = process.argv.slice(2);
const baseUrl = args.includes("--base") ? args[args.indexOf("--base") + 1] : "http://localhost:8000";
const email = process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = process.env.RADD_PROOF_PASSWORD ?? "change-me";

const { session, close } = await openBrowser({ port: 9371, profile: "/tmp/radd-settings-cleanup" });

/** The settings sidebar's visible tab labels. */
const NAV_LABELS =
  `[...document.querySelectorAll('nav[aria-label="Settings sections"] a')]` +
  `.map(a=>a.textContent.trim())`;

/** Every setting row's label on the surface currently rendered. */
const SETTING_LABELS =
  `[...document.querySelectorAll('p.text-\\\\[13px\\\\].font-medium.text-heading')]` +
  `.map(p=>p.textContent.trim())`;

const api = (path) =>
  `(async()=>{const r=await fetch("/api/v1${path}",{credentials:"include"});` +
  `return {status:r.status, body: await r.json().catch(()=>null)};})()`;

const post = (path) =>
  `(async()=>{const r=await fetch("/api/v1${path}",{method:"POST",credentials:"include"});` +
  `return r.status;})()`;

await session.navigate(baseUrl, 1500);
const loginStatus = await session.login(baseUrl, email, password);
const hoverCapable = await session.hoverCapable();

// --- 1. a plugin's settings tab is a property of the plugin ------------------
await session.navigate(`${baseUrl}/settings/general`, 2200);
const navWithForgejo = await session.eval(NAV_LABELS);

const plugins = await session.eval(api("/plugins"));
const forgejo = (plugins.body ?? []).find((p) => p.name === "forgejo");
const disableStatus = await session.eval(post(`/plugins/${forgejo?.id}/disable`));
// The manifest is what the sidebar reads; a reload is the honest way to see the
// new one (the app also invalidates it on the plugin page's own mutation).
await session.navigate(`${baseUrl}/settings/general`, 2500);
const navWithoutForgejo = await session.eval(NAV_LABELS);

const enableStatus = await session.eval(post(`/plugins/${forgejo?.id}/enable`));
await session.navigate(`${baseUrl}/settings/general`, 2500);
const navRestored = await session.eval(NAV_LABELS);

// --- 2/3. settings live where their owner declared -------------------------
const instanceGeneral = await session.eval(SETTING_LABELS);

await session.navigate(`${baseUrl}/settings/timelogging`, 2200);
const timeloggingPage = await session.eval(
  `({headings:[...document.querySelectorAll('h3')].map(h=>h.textContent.trim()),` +
  ` settings:${SETTING_LABELS}})`,
);

// The retired tabs' paths land somewhere real instead of a not-found.
await session.navigate(`${baseUrl}/settings/holidays`, 1800);
const holidaysLandsOn = await session.eval(`location.pathname`);
await session.navigate(`${baseUrl}/settings/groups`, 1800);
const groupsLandsOn = await session.eval(`location.pathname`);

// --- 2b. a project's General is the remainder, not the dump -----------------
const projects = await session.eval(api("/projects?limit=1"));
const projectKey = (projects.body ?? [])[0]?.key;

await session.navigate(`${baseUrl}/p/${projectKey}/settings/general`, 2400);
const projectGeneral = await session.eval(SETTING_LABELS);
await session.navigate(`${baseUrl}/p/${projectKey}/settings/releases`, 2400);
const projectReleases = await session.eval(SETTING_LABELS);
await session.navigate(`${baseUrl}/p/${projectKey}/settings/timelogging`, 2400);
const projectTimelogging = await session.eval(SETTING_LABELS);

// --- 4. one access model ----------------------------------------------------
await session.navigate(`${baseUrl}/p/${projectKey}/settings/access`, 2600);
const access = await session.eval(
  `({rows:document.querySelectorAll('ul.rounded-lg > li').length,` +
  ` grantControl: Boolean(document.querySelector('[aria-label="Role to grant"]')),` +
  ` subjectPicker: Boolean(document.querySelector('input[placeholder*="teams and directory groups"]')),` +
  ` legacyHeadings:[...document.querySelectorAll('h3')].map(h=>h.textContent.trim())})`,
);
// The endpoints the two folded tables used to serve are gone, not merely unused.
const legacyMembers = await session.eval(
  api(`/projects/${(projects.body ?? [])[0]?.id}/members`),
);
const legacyTeams = await session.eval(api(`/projects/${(projects.body ?? [])[0]?.id}/teams`));
// …and the read that replaced them answers.
const grantsByProject = await session.eval(
  api(`/role-grants?project_id=${(projects.body ?? [])[0]?.id}`),
);

await session.navigate(`${baseUrl}/settings/teams`, 3000);
// Scoped to a LIST ROW, not to `button[aria-expanded]` at large — the app
// shell's sidebar toggle carries that attribute and comes first in the
// document, so the unscoped selector expanded the sidebar and reported the
// settings nav's own sections as if they were the team panel's.
//
// Dispatched rather than hit-tested on purpose: this dev instance carries 2296
// teams, so where the first row lands is a fact about the scroll container, not
// about the panel under test.
//
// RADD-1046: zero teams (a freshly-seeded/clean instance) renders `EmptyState`
// instead of the `<ul class="rounded-lg">` list at all — see
// web/src/routes/settings/teams.tsx's `all.length === 0` branch — so this
// selector legitimately matches nothing there. That is a missing FIXTURE, not
// a regression, and the three checks below that read `expandedTeam`/`teamPanel`
// cannot mean anything without a row to expand: skip them by name rather than
// letting them fail (or, worse, pass vacuously — `teamPanel` is `[]` either
// way, so the "dropped its Projects section" check below would silently pass
// with no team ever having rendered at all).
const teamRowCount = await session.eval(
  `document.querySelectorAll('ul.rounded-lg > li > button[aria-expanded]').length`,
);
const hasTeamFixture = teamRowCount > 0;

let expandedTeam = null;
let teamPanel = [];
if (hasTeamFixture) {
  expandedTeam = await session.eval(
    `(()=>{const b=document.querySelector('ul.rounded-lg > li > button[aria-expanded]');
      if(!b) return null; b.click(); return b.textContent.trim().slice(0,40);})()`,
  );
  await sleep(1500);
  teamPanel = await session.eval(
    `[...document.querySelectorAll('section[aria-label]')].map(s=>s.getAttribute('aria-label'))`,
  );
}

const TEAM_ROW_LABELS = [
  "a team row actually expanded",
  "Teams panel dropped its Projects section",
  "…and kept the Roles section that replaces it",
];
if (!hasTeamFixture) {
  console.log(
    "no team fixture on this instance (zero rows in the Teams panel) — " +
      "skipping the team-row checks rather than failing or vacuously passing them:\n",
  );
  for (const label of TEAM_ROW_LABELS) {
    console.log(`skip ${label} (no team fixture — run against a seeded instance)`);
  }
  console.log("");
}

const failed = report(
  {
    "logged in": loginStatus === 204 || loginStatus === 200,
    "hover-capable browser (Tailwind gates hover: on it)": hoverCapable === true,

    "Forgejo tab present while its plugin is enabled": navWithForgejo.includes("Forgejo"),
    "disable succeeded": disableStatus === 200,
    "Forgejo tab WITHDRAWN when the plugin is disabled": !navWithoutForgejo.includes("Forgejo"),
    "non-plugin tabs survive the disable": navWithoutForgejo.includes("General"),
    "enable succeeded": enableStatus === 200,
    "Forgejo tab returns when re-enabled": navRestored.includes("Forgejo"),

    "Holidays is no longer a tab": !navRestored.includes("Holidays"),
    "Groups is no longer a tab": !navRestored.includes("Groups"),
    "Work categories renamed to Time logging": navRestored.includes("Time logging"),
    "Directory is a real tab now": navRestored.includes("Directory"),
    "/settings/holidays redirects to Time logging":
      holidaysLandsOn === "/settings/timelogging",
    "/settings/groups redirects to Directory": groupsLandsOn === "/settings/directory",

    "instance General sheds the directory keys": !instanceGeneral.some((l) =>
      l.startsWith("Bind account"),
    ),
    "instance General sheds the AI toggles": !instanceGeneral.includes("AI: summarize"),
    "instance General sheds the time keys": !instanceGeneral.includes("Working week"),

    "Time logging tab carries all three sections":
      timeloggingPage.headings.includes("Work categories") &&
      timeloggingPage.headings.includes("What a working day means") &&
      timeloggingPage.headings.includes("Holidays"),
    "…including the hours-per-day key": timeloggingPage.settings.includes(
      "Hours per working day",
    ),
    "…and the instance working week": timeloggingPage.settings.includes("Working week"),

    "project General no longer holds the release states":
      !projectGeneral.includes("Shipped state") &&
      !projectGeneral.includes("Waiting-for-release state"),
    "project General no longer holds the working week":
      !projectGeneral.includes("Working week"),
    "Shipped state moved to the Releases tab": projectReleases.includes("Shipped state"),
    "Waiting-for-release state moved with it":
      projectReleases.includes("Waiting-for-release state"),
    "working week moved to the Time logging tab":
      projectTimelogging.includes("Working week"),

    "project Access has a grant control": access.grantControl === true,
    "…over people, teams AND directory groups": access.subjectPicker === true,
    "…and no longer splits into two lists":
      !access.legacyHeadings.includes("Direct members") &&
      !access.legacyHeadings.includes("Team attachments"),
    "the members endpoint is gone": legacyMembers.status === 404,
    "the project-teams endpoint is gone": legacyTeams.status === 404,
    "grants are readable by project": grantsByProject.status === 200,

    // Fixture-dependent: these three mean nothing without a team row to
    // expand (RADD-1046) — omitted rather than failed or, worse, left to pass
    // VACUOUSLY, which is exactly what an unscoped `button[aria-expanded]`
    // selector did on the first run of this proof. The skip lines printed
    // above name them; `report`'s tally below never sees them when absent.
    ...(hasTeamFixture
      ? {
          [TEAM_ROW_LABELS[0]]: Boolean(expandedTeam),
          [TEAM_ROW_LABELS[1]]: !teamPanel.some((label) => label && label.endsWith(" projects")),
          [TEAM_ROW_LABELS[2]]: teamPanel.includes("Role grants"),
        }
      : {}),

    "no console errors": session.consoleErrors.length === 0,
  },
  {
    navWithForgejo,
    navWithoutForgejo,
    instanceGeneral,
    timeloggingPage,
    projectKey,
    projectGeneral,
    projectReleases,
    projectTimelogging,
    access,
    hasTeamFixture,
    teamRowCount,
    expandedTeam,
    teamPanel,
    consoleErrors: session.consoleErrors.slice(0, 5),
  },
);

close();
process.exit(failed ? 1 : 0);

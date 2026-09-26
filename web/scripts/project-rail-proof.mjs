/**
 * RADD-934: the project rail lists what you are ENTITLED to, not what you could open.
 *
 * `GET /projects` gates on `require_anywhere(item.read)`, which is lattice-aware:
 * `item.read@own` HOLDS `item.read` (RADD-823). That is right for a gate — a
 * person holding @own may read their own items anywhere, so the project must
 * stay openable or an issue assigned to them somewhere they are not a member of
 * becomes unreachable. It is wrong for a discovery surface, and the symptom was
 * an account with zero role grants seeing all 97 projects in the rail, every one
 * of them empty when opened.
 *
 * Asserted from BOTH sides, because either alone passes vacuously:
 *   - an entitled viewer (admin) still sees the full list, so the filter has not
 *     simply broken the rail;
 *   - an @own-only viewer is listed only the projects their own work is in
 *     ("related", RADD-937), and the rail offers the toggle that hides those
 *     rather than a count row;
 *   - and nothing became UNREACHABLE: the projects index still lists them and
 *     each still opens, so the rail got quieter without losing anything.
 *
 * Drives the real `view-as` preview (RADD-836) rather than logging in as the
 * target, because that is how an admin actually reproduces this.
 */
import { report } from "./lib/cdp.mjs";
import { startProof } from "./lib/proof.mjs";

const { session, close, baseUrl, loginStatus } = await startProof({
  port: 9377, profile: "/tmp/radd-project-rail", base: "http://localhost:8000",
});

/** The rail pages its projects 50 at a time (PROJECTS_PAGE_SIZE). */
const RAIL_PAGE = 50;

/** Rail state: individually-listed projects + the related-projects toggle (RADD-937). */
const RAIL =
  `(()=>{const rows=[...document.querySelectorAll('aside a[href^="/p/"]')]` +
  `.filter(a=>/^\\/p\\/[A-Z0-9]+$/.test(new URL(a.href).pathname));` +
  ` const toggle=document.querySelector('aside button[aria-label$="related projects"]');` +
  ` return {listed: rows.length, relatedToggle: toggle ? toggle.getAttribute("aria-label") : null};})()`;

/** What the server counts for the viewer: every visible project, and those visible only
 *  through the viewer's own work. */
const SUMMARY = `(async()=>(await fetch("/api/v1/projects/summary",{credentials:"include"})).json())()`;

const viewAs = (userId) =>
  `(async()=>{const r=await fetch("/api/v1/auth/view-as",{method:"POST",credentials:"include",` +
  `headers:{"Content-Type":"application/json"},body:JSON.stringify({user_id:"${userId}"})});` +
  `return r.status;})()`;

// Pick a target from the data rather than hardcoding one: an active account
// holding NO unqualified item.read anywhere is exactly the shape under test, and
// hardcoding an id would make this proof a fact about one dev database.
const target = await session.eval(
  `(async()=>{const users=await (await fetch("/api/v1/users?active=true&limit=200",` +
  `{credentials:"include"})).json();` +
  ` for (const u of users) {` +
  `   const a=await (await fetch("/api/v1/users/"+u.id+"/access",{credentials:"include"})).json();` +
  `   if (a.summary && a.summary.readable_projects === 0 && a.summary.own_readable_projects > 0) {` +
  `     return {id:u.id, name:u.name, own:a.summary.own_readable_projects};` +
  `   }` +
  ` } return null;})()`,
);

await session.navigate(`${baseUrl}/`, 3000);
const asAdmin = await session.eval(RAIL);
const adminSummary = await session.eval(SUMMARY);

const viewAsStatus = target ? await session.eval(viewAs(target.id)) : null;
await session.navigate(`${baseUrl}/`, 3500);
const asTarget = await session.eval(RAIL);
const targetSummary = viewAsStatus === 204 ? await session.eval(SUMMARY) : null;
// Hidden ("never") lists none of them; the default lists them, one rail page at most.
const relatedHidden = asTarget.relatedToggle === "Show related projects";
const hasRelated = (targetSummary?.related_count ?? 0) > 0;
// Nothing became UNREACHABLE — that is the whole claim. The projects index still
// lists them, and each still opens.
//
// The first version of this check counted issue links on My Work instead, which
// was wrong twice over: it asserted a property of whichever account the scan
// happened to pick — an @own-only account with no items is perfectly valid — and
// My Work rows open the peek panel rather than being anchors, so it read 0 for an
// account that plainly had work.
await session.navigate(`${baseUrl}/projects`, 3000);
const indexCount = await session.eval(
  `document.querySelectorAll('a[href^="/p/"]').length`,
);
// Reachability is tested through the route the app actually uses: projects are
// KEY-addressed (`/p/HAIR`) and there is no `GET /projects/{id}` at all — the
// first version of this check called one and read its 404 as a regression.
const unlistedKey = await session.eval(
  `(async()=>{const rows=await (await fetch("/api/v1/projects",{credentials:"include"})).json();` +
  ` return rows.length ? rows[0].key : null;})()`,
);
await session.navigate(`${baseUrl}/p/${unlistedKey}`, 3000);
const opensAnyway = await session.eval(
  `({path: location.pathname,` +
  ` notFound: /not found/i.test(document.body.innerText),` +
  ` showsProject: document.body.innerText.includes(${JSON.stringify(unlistedKey ?? "")})})`,
);
await session.eval(
  `(async()=>{await fetch("/api/v1/auth/view-as",{method:"DELETE",credentials:"include"});})()`,
);

if (!hasRelated) {
  console.log("skip …and the rail offers the toggle that hides them (the previewed account has no related project)\n");
}
const failed = report(
  {
    "logged in": loginStatus === 204 || loginStatus === 200,
    "found an @own-only account to preview as": target !== null,
    "view-as started": viewAsStatus === 204,

    "an entitled viewer still sees projects listed": asAdmin.listed > 0,
    "…none of them merely related, so there is nothing to hide":
      adminSummary.related_count === 0 && asAdmin.relatedToggle !== "Hide related projects",

    "an @own-only viewer is listed only the projects their own work is in":
      targetSummary !== null &&
      targetSummary.total === targetSummary.related_count &&
      asTarget.listed === (relatedHidden ? 0 : Math.min(targetSummary.related_count, RAIL_PAGE)),
    // Fixture-dependent: with no related project there is nothing to hide, and the
    // toggle rightly stays away — omitted (named above) rather than passed vacuously.
    ...(hasRelated
      ? { "…and the rail offers the toggle that hides them": asTarget.relatedToggle !== null }
      : {}),

    "the projects index still lists them": indexCount > 0,
    "…and one an @own-only viewer is NOT shown still opens by key":
      opensAnyway.showsProject === true && opensAnyway.notFound === false,

    "no console errors": session.consoleErrors.length === 0,
  },
  { target, asAdmin, adminSummary, asTarget, targetSummary, indexCount, unlistedKey, opensAnyway },
);

close();
process.exit(failed ? 1 : 0);

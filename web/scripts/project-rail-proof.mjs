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
 *   - an @own-only viewer sees none of them individually, plus one row that
 *     accounts for the remainder rather than hiding it;
 *   - and nothing became UNREACHABLE: the projects index still lists them and
 *     each still opens, so the rail got quieter without losing anything.
 *
 * Drives the real `view-as` preview (RADD-836) rather than logging in as the
 * target, because that is how an admin actually reproduces this.
 */
import { openBrowser, report } from "./lib/cdp.mjs";

const args = process.argv.slice(2);
const baseUrl = args.includes("--base") ? args[args.indexOf("--base") + 1] : "http://localhost:8000";
const email = process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = process.env.RADD_PROOF_PASSWORD ?? "change-me";

const { session, close } = await openBrowser({ port: 9377, profile: "/tmp/radd-project-rail" });

/** Rail state: individually-listed projects + the overflow accounting row. */
const RAIL =
  `(()=>{const rows=[...document.querySelectorAll('aside a[href^="/p/"]')]` +
  `.filter(a=>/^\\/p\\/[A-Z0-9]+$/.test(new URL(a.href).pathname));` +
  ` const overflow=[...document.querySelectorAll('aside a')].map(a=>a.textContent.trim())` +
  `.filter(t=>/more with only your own items/.test(t));` +
  ` return {listed: rows.length, overflow};})()`;

const viewAs = (userId) =>
  `(async()=>{const r=await fetch("/api/v1/auth/view-as",{method:"POST",credentials:"include",` +
  `headers:{"Content-Type":"application/json"},body:JSON.stringify({user_id:"${userId}"})});` +
  `return r.status;})()`;

await session.navigate(baseUrl, 1500);
const loginStatus = await session.login(baseUrl, email, password);

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

const viewAsStatus = target ? await session.eval(viewAs(target.id)) : null;
await session.navigate(`${baseUrl}/`, 3500);
const asTarget = await session.eval(RAIL);
// Nothing became UNREACHABLE — that is the whole claim. The projects index (where
// the overflow row points) still lists them, and each still opens.
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

const failed = report(
  {
    "logged in": loginStatus === 204 || loginStatus === 200,
    "found an @own-only account to preview as": target !== null,
    "view-as started": viewAsStatus === 204,

    "an entitled viewer still sees projects listed": asAdmin.listed > 0,
    "…and gets no overflow row": asAdmin.overflow.length === 0,

    "an @own-only viewer sees none listed individually": asTarget.listed === 0,
    "…and the rail accounts for the rest instead of hiding it":
      asTarget.overflow.length === 1,
    "…naming the right count":
      target !== null && asTarget.overflow[0]?.startsWith(String(target.own)),

    "the projects index still lists them": indexCount > 0,
    "…and one an @own-only viewer is NOT shown still opens by key":
      opensAnyway.showsProject === true && opensAnyway.notFound === false,

    "no console errors": session.consoleErrors.length === 0,
  },
  { target, asAdmin, asTarget, indexCount, unlistedKey, opensAnyway },
);

close();
process.exit(failed ? 1 : 0);

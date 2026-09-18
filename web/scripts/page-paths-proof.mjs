#!/usr/bin/env node
/**
 * RADD-1233 proof: pages are keyed by id and addressed by path.
 *
 *   node web/scripts/page-paths-proof.mjs http://localhost:8000 admin@example.com change-me
 *
 * Builds a throwaway space through the API — Engineering > Onboarding > Laptops,
 * Operations > Onboarding — and measures in a REAL browser that:
 *   1. two live pages named alike under different parents both keep the plain
 *      slug, and the tree links each by its PATH;
 *   2. the nested address `/pages/<space>/engineering/onboarding/laptops` opens
 *      the right page, with breadcrumbs that link by path;
 *   3. the permalink `/pages?pageId=<number>` redirects (history replace) to
 *      the readable path;
 *   4. a page renamed and moved is still reached by its OLD address, which
 *      redirects to the new one — and a same-named neighbour is not confused
 *      with it;
 *   5. a legacy single-segment `/pages/<space>/<slug>` link is NOT guessed at:
 *      only the page's recorded old addresses resolve;
 *   6. an archived "Onboarding" no longer blocks a new one: the new page is
 *      `onboarding`, not `onboarding-2`;
 *   7. the print view lives under /print and shows the path in its footer.
 * The space is deleted at the end.
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
if (!baseUrl || !adminEmail || !adminPassword) {
  console.error("usage: page-paths-proof.mjs <baseUrl> <adminEmail> <adminPassword>");
  process.exit(2);
}
const PORT = 9493;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-page-paths-proof");
const SLUG = `paths-proof-${Date.now().toString(36).slice(-5)}`;

const API = `
  const api = async (method, path, body) => {
    const r = await fetch("/api/v1" + path, {
      method, headers: { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await r.text();
    return { status: r.status, body: text ? JSON.parse(text) : null };
  };
`;

const VIEW = `(() => {
  const title = document.querySelector('input[aria-label="Page title"]')?.value ?? null;
  const tree = document.querySelector("[data-page-tree]");
  const treeLinks = tree ? [...tree.querySelectorAll("a")].map((a) => [a.textContent.trim(), a.getAttribute("href")]) : null;
  const crumbs = [...document.querySelectorAll("header a")].map((a) => [a.textContent.trim(), a.getAttribute("href")]);
  const archivedBanner = Boolean(document.querySelector("[data-archived-banner]"));
  const numberChip = document.querySelector("[data-page-number]");
  const permalink = numberChip ? [numberChip.textContent.trim(), numberChip.getAttribute("href")] : null;
  return { path: location.pathname, search: location.search, title, treeLinks, crumbs, archivedBanner, permalink };
})()`;

async function main() {
  const { session, close } = await openBrowser({ port: PORT, profile: PROFILE, width: 1500, height: 1000 });
  const checks = {};
  const context = { slug: SLUG };
  let spaceId = null;
  const view = () => session.eval(VIEW);
  const expand = async (title) => {
    await session.click(`button[aria-label="Expand ${title}"]`, () => true).catch(() => null);
    await sleep(250);
  };
  try {
    await session.navigate(baseUrl + "/login", 800);
    context.login = await session.login(baseUrl, adminEmail, adminPassword);

    const setup = await session.eval(`(async () => { ${API}
      const space = await api("POST", "/page-spaces", { name: "Paths proof", slug: ${JSON.stringify(SLUG)} });
      const sid = space.body.id;
      const mk = async (title, parent_id) => (await api("POST", "/pages", { space_id: sid, title, body: "body of " + title, parent_id })).body;
      const eng = await mk("Engineering", null);
      const ops = await mk("Operations", null);
      const engOnb = await mk("Onboarding", eng.id);
      const opsOnb = await mk("Onboarding", ops.id);
      const laptops = await mk("Laptops", engOnb.id);
      return { sid, eng, ops, engOnb, opsOnb, laptops };
    })()`);
    spaceId = setup.sid;
    const p = (s) => `/pages/${SLUG}/${s}`;

    // 1. same name, different parents: both plain; the tree links by path
    context.slugs = { engOnb: setup.engOnb.slug, opsOnb: setup.opsOnb.slug, paths: [setup.engOnb.path, setup.opsOnb.path, setup.laptops.path] };
    checks.siblingsElsewhereKeepThePlainSlug = setup.engOnb.slug === "onboarding" && setup.opsOnb.slug === "onboarding";
    checks.pathsAreDerivedFromTheTree =
      setup.engOnb.path === "engineering/onboarding" && setup.opsOnb.path === "operations/onboarding" && setup.laptops.path === "engineering/onboarding/laptops";
    checks.numbersAreSmallIntegers = Number.isInteger(setup.laptops.number) && setup.laptops.number > 0 && setup.laptops.number < 1e9;

    await session.navigate(`${baseUrl}${p("engineering/onboarding/laptops")}`, 2500);
    await expand("Engineering"); await expand("Onboarding"); await expand("Operations");
    let v = await view();
    context.nested = v;
    checks.nestedAddressOpensThePage = v.title === "Laptops" && v.path === p("engineering/onboarding/laptops");
    const treeHrefs = Object.fromEntries((v.treeLinks ?? []).map(([t, h]) => [h, t]));
    checks.treeLinksByPath =
      treeHrefs[p("engineering/onboarding")] === "Onboarding" && treeHrefs[p("operations/onboarding")] === "Onboarding" && treeHrefs[p("engineering/onboarding/laptops")] === "Laptops";
    checks.headerShowsTheNumberAsAPermalink =
      v.permalink?.[0] === `#${setup.laptops.number}` && v.permalink?.[1] === `/pages?pageId=${setup.laptops.number}`;
    checks.breadcrumbsLinkByPath = v.crumbs.some(([t, h]) => t === "Onboarding" && h === p("engineering/onboarding")) && v.crumbs.some(([t, h]) => t === "Engineering" && h === p("engineering"));
    await session.screenshot(resolve("scripts", "page-paths-proof-nested.png"));

    // 2. the permalink redirects to the path
    await session.navigate(`${baseUrl}/pages?pageId=${setup.laptops.number}`, 3000);
    v = await view();
    context.permalink = v;
    checks.permalinkRedirectsToThePath = v.path === p("engineering/onboarding/laptops") && v.search === "" && v.title === "Laptops";

    // 3. rename + move: the old address still lands, and redirects
    const moved = await session.eval(`(async () => { ${API}
      const renamed = await api("PATCH", "/pages/${setup.laptops.id}", { slug: "hardware" });
      const neighbour = (await api("POST", "/pages", { space_id: "${setup.sid}", title: "Hardware", body: "x", parent_id: "${setup.opsOnb.id}" })).body;
      const moved = await api("PATCH", "/pages/${setup.laptops.id}", { parent_id: "${setup.opsOnb.id}" });
      return { renamed: renamed.body.path, neighbour: neighbour.path, moved: moved.body.path, movedSlug: moved.body.slug };
    })()`);
    context.moved = moved;
    checks.moveBesideANamesakeYields = moved.movedSlug === "hardware-2" && moved.moved === "operations/onboarding/hardware-2" && moved.neighbour === "operations/onboarding/hardware";
    await session.navigate(`${baseUrl}${p("engineering/onboarding/laptops")}`, 3000);
    v = await view();
    context.staleOriginal = v;
    checks.originalAddressRedirectsToTheNewOne = v.title === "Laptops" && v.path === p("operations/onboarding/hardware-2");
    await session.navigate(`${baseUrl}${p("engineering/onboarding/hardware")}`, 3000);
    v = await view();
    context.staleRenamed = v;
    checks.renamedAddressRedirectsToo = v.title === "Laptops" && v.path === p("operations/onboarding/hardware-2");
    await session.navigate(`${baseUrl}${p("operations/onboarding/hardware")}`, 3000);
    v = await view();
    context.neighbour = v;
    checks.theNamesakeIsNotConfusedWithIt = v.title === "Hardware" && v.path === p("operations/onboarding/hardware");

    // 4. a bare segment that was never an address is not guessed at
    const bare = await session.eval(`(async () => { ${API} return (await api("GET", "/pages/by-path/${SLUG}/hardware-2")).status; })()`);
    context.bare = bare;
    checks.bareSegmentIsNotGuessedAt = bare === 404;

    // 5. archived pages do not squat on names
    const archived = await session.eval(`(async () => { ${API}
      await api("DELETE", "/pages/${setup.engOnb.id}");
      const fresh = (await api("POST", "/pages", { space_id: "${setup.sid}", title: "Onboarding", body: "new", parent_id: "${setup.eng.id}" })).body;
      return { slug: fresh.slug, path: fresh.path };
    })()`);
    context.archived = archived;
    checks.archivedNamesakeDoesNotBlockTheName = archived.slug === "onboarding" && archived.path === "engineering/onboarding";
    await session.navigate(`${baseUrl}${p("engineering/onboarding")}`, 2500);
    v = await view();
    context.livePage = v;
    checks.thePathNowMeansTheLivePage = v.title === "Onboarding" && !v.archivedBanner;

    // 6. the print view
    await session.navigate(`${baseUrl}/print/pages/${SLUG}/operations/onboarding/hardware-2`, 3500);
    const print = await session.eval(`(() => ({ mounted: Boolean(document.querySelector(".radd-print")), footer: document.querySelector(".radd-print-footer")?.textContent ?? "", title: document.querySelector(".radd-print h1")?.textContent ?? "" }))()`);
    context.print = print;
    checks.printViewLivesUnderItsOwnPrefix = print.mounted && print.title === "Laptops" && print.footer.includes(p("operations/onboarding/hardware-2"));
  } finally {
    if (spaceId) {
      await session.eval(`(async () => { ${API} return (await api("DELETE", "/page-spaces/${spaceId}?force=true")).status; })()`).catch(() => null);
    }
    await close();
  }
  report(checks, context);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

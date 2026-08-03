/**
 * Proves RADD-748: the insert menu is a faithful projection of the registry.
 *
 * "Shows icons" is the visible half. The half that matters is that every entry,
 * its icon and its grouping are read from `GET /pages/extensions` — so a plugin
 * that contributes a `PageExtensionSpec` appears with no frontend change. The
 * assertions therefore compare the rendered menu to what the SERVER says, row by
 * row, rather than to a list written here.
 *
 * The registry half — that a plugin's extension is recorded against that plugin,
 * and forgotten when it unmounts — is `tests/test_page_extensions.py`, because
 * nothing shipped contributes a page extension from another plugin yet, so there
 * is no plugin to enable in a browser.
 *
 * Usage: node scripts/extension-menu-proof.mjs <baseUrl> <spaceSlug> <email> <password>
 */
import { resolve } from "node:path";
import { HOVER_CAPABLE_PROBE, openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, spaceSlug, email, password] = process.argv.slice(2);
const PORT = 9453;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-ext-menu-proof");

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE, width: 1440, height: 1100 });
  const { consoleErrors } = session;

  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);

  const created = await session.eval(`(async () => {
    const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
    const space = spaces.find((s) => s.slug === ${JSON.stringify(spaceSlug)});
    const pages = await (await fetch("/api/v1/page-spaces/" + space.id + "/pages", {credentials:"include"})).json();
    let page = pages.find((p) => p.slug === "menu-proof");
    if (!page) {
      page = await (await fetch("/api/v1/pages", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ space_id: space.id, title: "Menu proof", body: "seed\\n" }),
      })).json();
    }
    return { id: page.id, slug: page.slug };
  })()`);

  await session.navigate(`${baseUrl}/pages/${spaceSlug}/${created.slug}`, 2500);
  await session.eval(`(() => { document.querySelector('button[aria-label="Edit page"]')?.click(); })()`);
  await sleep(3000);
  await session.click("svg.radd-extension-toolbar-icon");
  await sleep(800);

  const menu = await session.eval(`(async () => {
    const declared = await (await fetch("/api/v1/pages/extensions", {credentials:"include"})).json();
    const items = [...document.querySelectorAll('[role="menu"] [role="menuitem"]')];
    const rows = items.map((el) => {
      const svg = el.querySelector("svg");
      return {
        label: (el.querySelector("span span") || el).textContent.trim(),
        hasIcon: !!svg,
        // A rendered lucide icon has real geometry AND real path data. An <svg>
        // element that draws nothing would satisfy "hasIcon" while showing a gap.
        iconBox: svg ? svg.getBoundingClientRect().width : 0,
        iconPaths: svg ? svg.querySelectorAll("path, circle, rect, line, polyline, ellipse, polygon").length : 0,
      };
    });
    // Every rendered row must be inside the menu's own box — the list scrolls,
    // and a row painted outside it cannot be clicked (RADD-742's shape).
    const menuBox = document.querySelector('[role="menu"]')?.getBoundingClientRect();
    return {
      declaredLabels: declared.map((d) => d.label).sort(),
      declaredIcons: declared.map((d) => d.icon),
      declaredSources: [...new Set(declared.map((d) => d.source))],
      rows,
      rowLabels: rows.map((r) => r.label).sort(),
      headings: [...document.querySelectorAll('[role="menu"] p')].map((p) => p.textContent.trim()),
      menuHeight: menuBox ? menuBox.height : 0,
      viewportHeight: window.innerHeight,
    };
  })()`);

  const hoverCapable = await session.eval(HOVER_CAPABLE_PROBE);

  const withIcons = menu.rows.filter((r) => r.hasIcon && r.iconBox > 0 && r.iconPaths > 0);
  const declaredWithIcon = menu.declaredIcons.filter(Boolean).length;

  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    // The registry IS the menu — not a list in the SPA.
    "the menu lists exactly what the registry declares":
      menu.declaredLabels.length > 0 &&
      JSON.stringify(menu.rowLabels) === JSON.stringify(menu.declaredLabels),
    "every entry the registry gives an icon renders one":
      declaredWithIcon > 0 && withIcons.length === declaredWithIcon,
    "the icons are drawn, not empty svg elements":
      withIcons.length > 0 && withIcons.every((r) => r.iconPaths > 0 && r.iconBox >= 12),
    "the server says which plugin each entry came from":
      menu.declaredSources.length > 0 && menu.declaredSources.every(Boolean),
    // One contributor today: a heading would label the whole list.
    "a single contributor gets no redundant heading":
      menu.declaredSources.length > 1 || menu.headings.length === 1,
    // Regression on what RADD-747 found: seven entries overflowed the old
    // max-h-80 list, which put a real entry outside its own clickable box.
    "the whole list fits on screen at 1100px":
      menu.menuHeight > 0 && menu.menuHeight <= menu.viewportHeight,
    "no console errors": consoleErrors.length === 0,
  };

  return report(checks, { menu, hoverCapable, consoleErrors });
}

main()
  .then((failed) => process.exit(failed ? 1 : 0))
  .catch((err) => { console.error(err); process.exit(2); });

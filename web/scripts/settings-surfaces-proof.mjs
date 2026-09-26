/**
 * Browser proof for RADD-1390 against the REAL backend: no host list decides where a plugin's
 * settings live or which icon its nav entry shows.
 *
 *   1. Settings → General renders exactly the instance rows no plugin homes (`homed` = false);
 *   2. every contributed settings-nav entry draws the icon its manifest names (a lucide class
 *      derived from the kebab-case name), not the fallback — Automations' Zap included;
 *   3. no console errors.
 *
 * Usage: node scripts/settings-surfaces-proof.mjs <baseUrl> [email] [password]
 */
import { resolve } from "node:path";
import { waitFor } from "./lib/cdp.mjs";
import { startProof } from "./lib/proof.mjs";

const { session, close, check, finish, baseUrl } = await startProof({
  port: 9490, profile: resolve(process.env.TMPDIR || "/tmp", "radd-settings-surfaces-proof"),
});
try {
  const rows = await session.eval(`fetch("/api/v1/scoped-settings?scope=instance").then((r) => r.json())`);
  const unhomed = rows.filter((r) => !r.homed).map((r) => r.label || r.key);
  check("some instance rows are homed by their plugins, some are left for General",
    rows.some((r) => r.homed) && unhomed.length > 0, `${rows.length} rows, ${unhomed.length} unhomed`);

  await session.navigate(`${baseUrl}/settings/general`, 300);
  await waitFor(session, `document.body.innerText.includes(${JSON.stringify(unhomed[0])}) && document.querySelectorAll('nav[aria-label="Settings sections"] a').length > 10`);
  const text = await session.eval(`document.querySelector("main")?.innerText ?? document.body.innerText`);
  check("General shows every unhomed row", unhomed.every((label) => text.includes(label)),
    unhomed.filter((label) => !text.includes(label)).join(", "));
  const homed = rows.filter((r) => r.homed && r.label && !unhomed.includes(r.label)).map((r) => r.label);
  check("General shows no homed row", homed.every((label) => !text.includes(label)),
    homed.filter((label) => text.includes(label)).join(", "));

  const caps = await session.eval(`fetch("/api/v1/capabilities").then((r) => r.json())`);
  const nav = caps.nav.filter((n) => n.section === "settings");
  const drawn = await session.eval(`Object.fromEntries([...document.querySelectorAll('nav[aria-label="Settings sections"] a')]
    .map((a) => [a.getAttribute("href"), a.querySelector("svg")?.getAttribute("class") ?? ""]))`);
  for (const item of nav) {
    const cls = drawn[item.path] ?? "missing";
    check(`${item.label} draws its declared icon "${item.icon}"`, cls.includes(`lucide-${item.icon}`), cls);
  }
  check("no console errors", session.consoleErrors.length === 0, session.consoleErrors.slice(0, 3).join(" | "));
} finally {
  await close();
}
finish({ proof: "settings surfaces" });

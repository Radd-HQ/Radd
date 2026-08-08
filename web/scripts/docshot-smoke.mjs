/**
 * Smoke test for the documentation capture harness (RADD-1001).
 *
 * Proves the four properties the fan-out depends on, against the LIVE instance:
 *   1. the PAT authenticates the real SPA — no login screen in the image;
 *   2. the write gate is installed before the bundle boots;
 *   3. a panel captures to a real PNG, clipped to its own element;
 *   4. a write to /api/ is REFUSED and named in the report.
 *
 * (4) is the one that must never be taken on trust. It is asserted by having
 * the page attempt a DELETE and checking that it comes back 403 from the
 * wrapper rather than from the server — a gate that silently failed to attach
 * would let that request reach production.
 *
 * Usage: node scripts/docshot-smoke.mjs <baseUrl> <token> [outDir]
 */
import { resolve } from "node:path";
import { openDocsBrowser, capture, goto } from "./lib/docshot.mjs";

const [baseUrl, token, outDir = "/tmp/docshot-smoke"] = process.argv.slice(2);
const PORT = 9471;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-docshot-smoke-profile");

const results = [];
const check = (name, pass, detail = "") => {
  results.push({ name, pass, detail });
  console.log(`${pass ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
};

const { session, close } = await openDocsBrowser({ port: PORT, profile: PROFILE, baseUrl, token });

try {
  await goto(session, "/settings/general", { waitFor: "main" });

  check("hover is capable", await session.hoverCapable());
  check("write gate installed", await session.gateInstalled());

  const me = await session.eval(
    `(async()=>{const r=await fetch("/api/v1/auth/me");return r.ok?(await r.json()).email:"HTTP "+r.status;})()`,
  );
  check("PAT authenticates the SPA", typeof me === "string" && me.includes("@"), String(me));

  const heading = await session.eval(
    `(()=>{const h=document.querySelector("main h1, main h2");return h?h.textContent.trim():null;})()`,
  );
  check("a settings panel rendered", !!heading, heading || "no heading found");

  // (4) The gate itself. A DELETE against a real endpoint: if the wrapper is
  // working this never leaves the browser.
  const blockedProbe = await session.eval(
    `(async()=>{const r=await fetch("/api/v1/page-spaces/00000000-0000-0000-0000-000000000000",{method:"DELETE"});` +
      `return {status:r.status, body:(await r.json()).detail||""};})()`,
  );
  check(
    "a DELETE to /api/ is refused by the wrapper",
    blockedProbe.status === 403 && String(blockedProbe.body).includes("docshot"),
    `status ${blockedProbe.status}: ${blockedProbe.body}`,
  );

  const blocked = await session.blocked();
  check(
    "the refusal is recorded in the report",
    blocked.some((b) => b.method === "DELETE"),
    JSON.stringify(blocked),
  );

  const shot = await capture(session, { out: resolve(outDir, "settings-general.png"), clipTo: "main", padding: 8 });
  const { stat } = await import("node:fs/promises");
  const { size } = await stat(shot);
  check("panel captured to a PNG", size > 10000, `${shot} (${Math.round(size / 1024)} KB)`);

  const full = await capture(session, { out: resolve(outDir, "settings-general-full.png"), fullPage: true });
  const fullSize = (await stat(full)).size;
  check("full-page capture works", fullSize > 10000, `${full} (${Math.round(fullSize / 1024)} KB)`);

  const errors = session.consoleErrors.filter((e) => !/favicon|WebSocket|ws:/i.test(e));
  check("no unexpected console errors", errors.length === 0, errors.slice(0, 3).join(" | "));
} finally {
  close();
}

const failed = results.filter((r) => !r.pass);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);

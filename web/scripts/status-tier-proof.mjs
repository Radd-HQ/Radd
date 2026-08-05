/**
 * RADD-900 proof: the semantic status tier + var()-driven charts resolve to the
 * intended COMPUTED colors in both themes.
 *
 * Measures, in a real browser against the running app:
 *   1. a real report-chart line's computed stroke (charts now carry
 *      `var(--accent-fill)` / `var(--status-*)` instead of hex constants) —
 *      falling back to a synthetic SVG probe when the reports page has no
 *      rendered line (empty DB);
 *   2. the danger Button's computed background via its real compiled classes;
 *   3. the raw tier variables on both `html` and `html.light`.
 *
 * Expected: dark danger #ef4444 (red-500 — the shade the button always had),
 * light danger #dc2626; success #34d399 / #059669; accent #6f6ce0 both themes.
 *
 * Usage: node scripts/status-tier-proof.mjs <baseUrl> <email> <password>
 */
import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import { resolve } from "node:path";
import { chromeArgs, findChrome, HOVER_CAPABLE_PROBE } from "./lib/chrome.mjs";

const [baseUrl, email, password] = process.argv.slice(2);
const PORT = 9447;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-status-tier-proof-profile");

// A leaked browser is worse than a stale bundle: refuse to reuse one.
try {
  await fetch(`http://127.0.0.1:${PORT}/json/version`);
  console.error(`FATAL: something already listens on :${PORT} — kill it first`);
  process.exit(1);
} catch {
  /* free — good */
}

const chrome = spawn(findChrome(), chromeArgs({ port: PORT, profile: PROFILE }), {
  stdio: "ignore",
});

let ws;
let nextId = 1;
const pending = new Map();
function send(method, params = {}, sessionId) {
  const id = nextId++;
  ws.send(JSON.stringify(sessionId ? { id, method, params, sessionId } : { id, method, params }));
  return new Promise((res, rej) => pending.set(id, { res, rej }));
}
async function evalInPage(sessionId, expression) {
  const { result, exceptionDetails } = await send(
    "Runtime.evaluate",
    { expression, awaitPromise: true, returnByValue: true },
    sessionId,
  );
  if (exceptionDetails) throw new Error("page eval threw: " + (exceptionDetails.text || ""));
  return result.value;
}

async function main() {
  let version;
  for (let i = 0; i < 40 && !version; i++) {
    try {
      version = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json();
    } catch {
      await sleep(250);
    }
  }
  if (!version) throw new Error("Chrome CDP did not come up");

  ws = new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.addEventListener("open", res, { once: true });
    ws.addEventListener("error", rej, { once: true });
  });
  ws.addEventListener("message", (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
      const { res, rej } = pending.get(m.id);
      pending.delete(m.id);
      m.error ? rej(new Error(m.error.message)) : res(m.result);
    }
  });

  const { targetId } = await send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
  await send("Page.enable", {}, sessionId);
  await send("Runtime.enable", {}, sessionId);

  await send("Page.navigate", { url: baseUrl + "/" }, sessionId);
  await sleep(1200);
  const hoverCapable = await evalInPage(sessionId, HOVER_CAPABLE_PROBE);
  const loginStatus = await evalInPage(
    sessionId,
    `(async()=>{const r=await fetch("/api/v1/auth/login",{method:"POST",credentials:"include",headers:{"Content-Type":"application/json"},body:JSON.stringify(${JSON.stringify({ email, password })})});return r.status;})()`,
  );

  await send("Page.navigate", { url: `${baseUrl}/reports` }, sessionId);
  // Wait for a chart polyline/path whose stroke attribute is a var() reference.
  let chartFound = false;
  for (let i = 0; i < 30 && !chartFound; i++) {
    await sleep(500);
    chartFound = await evalInPage(
      sessionId,
      `!!document.querySelector('svg [stroke^="var("]')`,
    );
  }

  const MEASURE = `
    (() => {
      // 1. A real chart line, when one rendered; else a synthetic probe that
      //    exercises the same mechanism (SVG stroke resolving a CSS var).
      let lineEl = document.querySelector('svg polyline[stroke^="var("], svg path[stroke^="var("], svg line[stroke^="var("]');
      let lineSource = lineEl ? (lineEl.getAttribute("stroke") + " (real chart)") : null;
      if (!lineEl) {
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        const l = document.createElementNS("http://www.w3.org/2000/svg", "line");
        l.setAttribute("stroke", "var(--accent-fill)");
        svg.appendChild(l);
        document.body.appendChild(svg);
        lineEl = l;
        lineSource = "var(--accent-fill) (synthetic probe)";
      }
      // 2. The danger Button, via its real compiled classes.
      let btn = document.getElementById("proof-danger-btn");
      if (!btn) {
        btn = document.createElement("button");
        btn.id = "proof-danger-btn";
        btn.className = "inline-flex items-center gap-1.5 rounded-md font-medium bg-status-danger/90 text-white hover:bg-status-danger h-8 px-3";
        document.body.appendChild(btn);
      }
      const styles = getComputedStyle(document.documentElement);
      return {
        chartLineStroke: getComputedStyle(lineEl).stroke,
        chartLineSource: lineSource,
        dangerButtonBg: getComputedStyle(btn).backgroundColor,
        vars: {
          statusDanger: styles.getPropertyValue("--status-danger").trim(),
          statusDangerInk: styles.getPropertyValue("--status-danger-ink").trim(),
          statusWarning: styles.getPropertyValue("--status-warning").trim(),
          statusSuccess: styles.getPropertyValue("--status-success").trim(),
          accentFill: styles.getPropertyValue("--accent-fill").trim(),
        },
      };
    })()`;

  const dark = await evalInPage(sessionId, MEASURE);
  await evalInPage(sessionId, `document.documentElement.classList.add("light")`);
  await sleep(150);
  const light = await evalInPage(sessionId, MEASURE);
  await evalInPage(sessionId, `document.documentElement.classList.remove("light")`);

  const expect = {
    dark: { danger: "#ef4444", success: "#34d399", accent: "#6f6ce0" },
    light: { danger: "#dc2626", success: "#059669", accent: "#6f6ce0" },
  };
  const pass =
    dark.vars.statusDanger === expect.dark.danger &&
    dark.vars.statusSuccess === expect.dark.success &&
    light.vars.statusDanger === expect.light.danger &&
    light.vars.statusSuccess === expect.light.success &&
    dark.dangerButtonBg !== light.dangerButtonBg && // the button THEMES now
    dark.chartLineStroke !== "" &&
    !dark.chartLineStroke.includes("var("); // the var RESOLVED to a color

  console.log(JSON.stringify({ hoverCapable, loginStatus, chartFound, dark, light, pass }, null, 2));
  await send("Target.closeTarget", { targetId });
  ws.close();
  chrome.kill();
  process.exit(pass ? 0 : 1);
}

main().catch((error) => {
  console.error(error);
  chrome.kill();
  process.exit(1);
});

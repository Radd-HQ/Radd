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
import { resolve } from "node:path";
import { openBrowser, sleep } from "./lib/cdp.mjs";

const [baseUrl, email, password] = process.argv.slice(2);

async function main() {
  const { session, close } = await openBrowser({
    port: 9447, profile: resolve(process.env.TMPDIR || "/tmp", "radd-status-tier-proof-profile"),
  });
  await session.navigate(baseUrl + "/", 1200);
  const hoverCapable = await session.hoverCapable();
  const loginStatus = await session.login(baseUrl, email, password);

  await session.navigate(`${baseUrl}/reports`, 0);
  // Wait for a chart polyline/path whose stroke attribute is a var() reference.
  let chartFound = false;
  for (let i = 0; i < 30 && !chartFound; i++) {
    await sleep(500);
    chartFound = await session.eval(`!!document.querySelector('svg [stroke^="var("]')`);
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

  const dark = await session.eval(MEASURE);
  await session.eval(`document.documentElement.classList.add("light")`);
  await sleep(150);
  const light = await session.eval(MEASURE);
  await session.eval(`document.documentElement.classList.remove("light")`);

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
  await close();
  process.exit(pass ? 0 : 1);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

/**
 * Does a ```mermaid fence actually draw? (RADD-1024)
 *
 * A diagram that "renders" is easy to fake: an empty <svg> is still an <svg>.
 * So this asks for evidence the graph was really laid out — nodes, edges, and a
 * non-zero size — and checks that a diagram with a syntax error reports the
 * error rather than blanking the page or taking the rest of it down.
 *
 * Usage:
 *   node scripts/mermaid-proof.mjs <baseUrl> <spaceSlug> <pageSlug> <email> <password>
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, spaceSlug, pageSlug, email, password] = process.argv.slice(2);
const PORT = 9457;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-mermaid-proof");

const PROBE = `(() => {
  const frames = [...document.querySelectorAll("[data-mermaid]")];
  const svgs = frames.map((f) => f.querySelector("svg")).filter(Boolean);
  const box = svgs.map((s) => {
    const r = s.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height) };
  });
  const body = (document.querySelector("main") || document.body).textContent || "";
  return {
    diagramFrames: frames.length,
    svgs: svgs.length,
    boxes: box,
    // Real layout leaves nodes and edges behind; an empty <svg> leaves neither.
    nodes: svgs.reduce((n, s) => n + s.querySelectorAll(".node, .nodes > g").length, 0),
    edges: svgs.reduce((n, s) => n + s.querySelectorAll(".edgePath, .edgePaths > g, path.flowchart-link").length, 0),
    // The broken diagram must SAY so.
    reportsAnError: body.includes("could not be drawn"),
    // …and must not leak mermaid's own error graphic into the document.
    strayMermaidError: document.querySelectorAll("[id^=dmermaid], .error-icon").length,
    leakedFence: body.includes("graph TD") && frames.length > 0 && body.includes("sequenceDiagram") === false,
  };
})()`;

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE });
  const checks = {};

  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);
  checks["headless chrome reports a real pointer"] = await session.hoverCapable();

  await session.navigate(`${baseUrl}/pages/${spaceSlug}/${pageSlug}`, 3000);
  await sleep(2500); // mermaid is loaded on demand; give the chunk time to land
  const seen = await session.eval(PROBE);

  checks["both valid diagrams rendered an <svg>"] = seen.svgs >= 2;
  checks["…with real layout (nodes)"] = seen.nodes > 0;
  checks["…and edges between them"] = seen.edges > 0;
  checks["…at a non-zero size"] =
    seen.boxes.length > 0 && seen.boxes.every((b) => b.w > 0 && b.h > 0);
  checks["the broken diagram reports its error"] = seen.reportsAnError === true;
  checks["…without leaking mermaid's own error graphic"] = seen.strayMermaidError === 0;

  const shot = await session.send("Page.captureScreenshot", { format: "png" });
  report(checks, seen);
  return shot.data;
}

main()
  .then(async (png) => {
    const { writeFile } = await import("node:fs/promises");
    const dir = process.env.PROOF_OUT || "/tmp";
    await writeFile(`${dir}/mermaid.png`, Buffer.from(png, "base64"));
    console.log(`screenshot: ${dir}/mermaid.png`);
    process.exit(0);
  })
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });

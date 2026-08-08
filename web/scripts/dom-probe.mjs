/**
 * One-off: ask a rendered page what its body actually became.
 *
 * Used to characterise the fenced-code-block render failure — specifically
 * whether code-block content reaches the DOM as real markup, which is the
 * difference between a rendering bug and an injection one.
 *
 * usage: node scripts/dom-probe.mjs <path> [--port N]
 */
import { resolve } from "node:path";
import { homedir } from "node:os";
import { readFile } from "node:fs/promises";
import { openDocsBrowser, goto } from "./lib/docshot.mjs";

const argv = process.argv.slice(2);
const path = argv[0];
const i = argv.indexOf("--port");
const port = Number(i >= 0 ? argv[i + 1] : 9520);

const token =
  process.env.RADD_API_TOKEN ||
  (await readFile(resolve(homedir(), ".radd-token"), "utf8").catch(() => "")).trim();

const { session, close } = await openDocsBrowser({
  port,
  profile: resolve("/tmp", `radd-domprobe-${port}`),
  baseUrl: process.env.RADD_DOCS_URL || "https://project.radd-hq.com",
  token,
});

try {
  await goto(session, path, { waitFor: "[data-page-body]" });
  // PageBody renders ASYNCHRONOUSLY — Crepe creates each prose run on its own
  // schedule and counts readiness. `[data-page-body]` exists long before any of
  // it is in the DOM, so a probe that stops there reports an empty document and
  // reads exactly like a rendering bug. Wait for the node count to stop moving.
  let last = -1;
  let stable = 0;
  for (let i = 0; i < 80 && stable < 4; i++) {
    const count = await session.eval(
      `document.querySelectorAll("[data-page-body] h1,[data-page-body] h2,[data-page-body] h3,[data-page-body] p,[data-page-body] pre").length`,
    );
    stable = count === last && count > 0 ? stable + 1 : 0;
    last = count;
    await new Promise((r) => setTimeout(r, 250));
  }
  console.error(`settled at ${last} block node(s)`);

  const info = await session.eval(`(() => {
    const body = document.querySelector("[data-page-body]");
    const injected = document.querySelector("#docshot-dom-probe");
    const shape = [];
    const walk = (el, depth) => {
      for (const child of el.children) {
        if (depth < 3) shape.push("  ".repeat(depth) + child.tagName.toLowerCase()
          + (child.className && typeof child.className === "string" ? "." + child.className.split(/\\s+/)[0] : ""));
        if (depth < 3) walk(child, depth + 1);
      }
    };
    if (body) walk(body, 0);
    return {
      hasBody: !!body,
      injectedElementPresent: !!injected,
      injectedTag: injected ? injected.tagName : null,
      headings: body ? [...body.querySelectorAll("h1,h2,h3")].map((h) => h.tagName + ": " + h.textContent.trim()) : [],
      codeBlocks: body ? [...body.querySelectorAll("pre")].map((p) => p.textContent.trim().slice(0, 80)) : [],
      shape: shape.slice(0, 40),
    };
  })()`);
  console.log(JSON.stringify(info, null, 2));
} finally {
  close();
}

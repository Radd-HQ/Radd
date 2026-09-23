#!/usr/bin/env node
/**
 * Proof for RADD-1296 (GitHub radd-hq/radd#20): checklists you can read and
 * tick without opening the editor.
 *
 *   node web/scripts/task-toggle-proof.mjs http://127.0.0.1:8000 admin@example.com change-me
 *
 *   1. a box is a real 16px box, not a 13px glyph; open vs done differ in
 *      FILL, and the open box's border clears 3:1 against the page in BOTH
 *      themes (a graphic, so 3:1, not 4.5:1);
 *   2. a done item's own text is struck through; its open nested child is not;
 *   3. ticking in a description's READ view persists, with no editor opened,
 *      and changes exactly one line of the stored text;
 *   4. the same on a comment;
 *   5. on a wiki page split by a `radd:toc` block, ticking the box AFTER the
 *      block flips the right line (the index counts across segments), and it
 *      is a versioned save;
 *   6. a description edited behind the reader's back is REFUSED, not
 *      overwritten — the stored text keeps the other edit.
 * Fixtures are deleted at the end.
 */
import { resolve } from "node:path";
import { clickAt, openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
if (!baseUrl || !adminEmail || !adminPassword) {
  console.error("usage: task-toggle-proof.mjs <baseUrl> <adminEmail> <adminPassword>");
  process.exit(2);
}
const PORT = 9498;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-task-toggle-proof");
const SHOTS = resolve(process.env.TMPDIR || "/tmp", "radd-task-toggle-proof-shots");
const STAMP = Date.now().toString(36).slice(-5);
const KEY = `TK${STAMP.slice(-4).toUpperCase()}`;

const DESCRIPTION = [
  "Release checklist",
  "",
  "- [x] Write the notes",
  "  - [ ] Nested and still open",
  "- [ ] Tag the version",
  "- [ ] Sweep the release",
].join("\n");
const COMMENT = "- [ ] Reply to the reporter\n- [ ] Close the thread";
const PAGE = ["- [ ] Before the block", "", "```radd:toc", "```", "", "- [ ] After the block"].join("\n");

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

// :is(), because a bare comma list inside a compound selector ("[x] .a, .b")
// matches ".b" ANYWHERE — the first run clicked the description for the comment.
const LABEL = ":is(.label.checked, .label.unchecked)";

/** Measure every task box in the first viewer under `scope`. */
const measure = (scope) => `(() => {
  const lum = (c) => { const m = c.match(/[\\d.]+/g).map(Number); const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(m[0]) + 0.7152 * f(m[1]) + 0.0722 * f(m[2]); };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const bgOf = (el) => { while (el) { const c = getComputedStyle(el).backgroundColor; if (c && !c.endsWith(", 0)") && c !== "transparent") return c; el = el.parentElement; } return "rgb(0, 0, 0)"; };
  const root = document.querySelector(${JSON.stringify(scope)});
  return [...(root?.querySelectorAll(${JSON.stringify(LABEL)}) ?? [])].map((label) => {
    const s = getComputedStyle(label); const r = label.getBoundingClientRect();
    const p = label.closest(".list-item")?.querySelector(":scope > .children > .content-dom > p");
    return { checked: label.classList.contains("checked"), w: r.width, h: r.height, fill: s.backgroundColor,
      border: s.borderTopColor, contrast: ratio(s.borderTopColor, bgOf(label.parentElement)),
      strike: p ? getComputedStyle(p).textDecorationLine : null, text: p?.textContent ?? "",
      role: label.getAttribute("role"), aria: label.getAttribute("aria-checked"),
      // How far the box's centre sits from the centre of its text's FIRST line.
      offset: p ? Math.abs((r.top + r.height / 2) - (p.getBoundingClientRect().top + parseFloat(getComputedStyle(p).lineHeight) / 2)) : 99 };
  });
})()`;

async function main() {
  const { session, close } = await openBrowser({ port: PORT, profile: PROFILE, width: 1400, height: 1000, scale: 2 });
  const send = session.send;
  const checks = {};
  const context = { key: KEY };
  let fixture = null;
  try {
    await session.navigate(baseUrl + "/login", 800);
    await session.login(baseUrl, adminEmail, adminPassword);
    fixture = await session.eval(`(async () => { ${API}
      const project = await api("POST", "/projects", { key: ${JSON.stringify(KEY)}, name: "Task toggle proof" });
      const item = await api("POST", "/items", { project_id: project.body.id, title: "Checklist item", description: ${JSON.stringify(DESCRIPTION)} });
      const comment = await api("POST", "/items/" + item.body.id + "/comments", { body: ${JSON.stringify(COMMENT)} });
      const space = await api("POST", "/page-spaces", { name: "Task proof", slug: "task-proof-${STAMP}" });
      const page = await api("POST", "/pages", { space_id: space.body.id, title: "Checklist page", body: ${JSON.stringify(PAGE)} });
      return { project: project.body, item: item.body, comment: comment.body, space: space.body, page: page.body };
    })()`);

    // --- the issue view ----------------------------------------------------
    await session.navigate(`${baseUrl}/issues/${fixture.item.key}`, 3500);
    const scope = "[data-task-toggle]";
    const boxes = await session.eval(measure(scope));
    context.boxes = boxes.map(({ checked, w, fill, contrast, strike, text }) => ({ checked, w, fill, contrast: +contrast.toFixed(2), strike, text }));
    const open = boxes.find((b) => !b.checked);
    const done = boxes.find((b) => b.checked);
    checks["1a. boxes are 16px squares, not glyphs"] = boxes.length === 4 && boxes.every((b) => b.w === 16 && b.h === 16);
    checks["1b. done and open differ in fill"] = !!open && !!done && open.fill !== done.fill;
    checks["1c. the open box's border clears 3:1 (dark)"] = !!open && open.contrast >= 3;
    context.offsets = boxes.map((b) => +b.offset.toFixed(1));
    checks["1f. each box sits beside its text's first line (centres within 3px)"] = boxes.every((b) => b.offset <= 3);
    checks["1d. boxes are checkboxes to assistive tech"] = boxes.every((b) => b.role === "checkbox" && b.aria === String(b.checked));
    checks["2. a done item is struck through; its open nested child is not"] =
      done?.strike === "line-through" && boxes.find((b) => b.text.startsWith("Nested"))?.strike === "none";
    await session.eval(`document.documentElement.classList.add("light")`);
    await sleep(300);
    const light = await session.eval(measure(scope));
    context.lightContrast = +(light.find((b) => !b.checked)?.contrast ?? 0).toFixed(2);
    checks["1e. the open box's border clears 3:1 (light)"] = context.lightContrast >= 3;
    await session.screenshot(resolve(SHOTS, "description-light.png"));
    await session.eval(`document.documentElement.classList.remove("light")`);
    await sleep(200);
    await session.screenshot(resolve(SHOTS, "description-dark.png"));

    // 3 — tick "Tag the version" (task index 2) in read mode.
    await session.eval(`(() => {
      const labels = document.querySelector(${JSON.stringify(scope)}).querySelectorAll(${JSON.stringify(LABEL)});
      labels[2].setAttribute("data-proof-target", "");
    })()`);
    // The issue page always carries one editable ProseMirror — the comment
    // composer — so "no editor opened" is a count that must not grow.
    const editorsBefore = await session.eval(`document.querySelectorAll(".ProseMirror[contenteditable=true]").length`);
    await clickAt(send, "[data-proof-target]");
    await sleep(1800);
    const after = await session.eval(`(async () => { ${API}
      return { description: (await api("GET", "/items/${fixture.item.id}")).body.description,
        editorOpen: document.querySelectorAll(".ProseMirror[contenteditable=true]").length > ${editorsBefore} };
    })()`);
    const changed = DESCRIPTION.split("\n").filter((line, i) => line !== after.description.split("\n")[i]);
    context.changedLines = changed;
    checks["3a. a read-mode tick persists"] = after.description.includes("- [x] Tag the version");
    checks["3b. …changing exactly one line"] = changed.length === 1 && changed[0] === "- [ ] Tag the version";
    checks["3c. …with no editor opened"] = !after.editorOpen;
    await session.screenshot(resolve(SHOTS, "description-ticked.png"));

    // 4 — a comment.
    context.commentProbe = await session.eval(`(() => {
      const row = document.querySelector('[data-comment-id="${fixture.comment.id}"]');
      return { row: !!row, toggle: !!row?.querySelector("[data-task-toggle]"), labels: row?.querySelectorAll(${JSON.stringify(LABEL)}).length ?? 0 };
    })()`);
    context.commentClick = await clickAt(send, `[data-comment-id="${fixture.comment.id}"] ${LABEL}`);
    await sleep(1800);
    const comment = await session.eval(`(async () => { ${API}
      const feed = await api("GET", "/items/${fixture.item.id}/comments");
      const rows = Array.isArray(feed.body) ? feed.body : (feed.body.comments ?? feed.body.items ?? []);
      return rows.find((c) => c.id === ${JSON.stringify(fixture.comment.id)})?.body ?? null;
    })()`);
    context.comment = comment;
    checks["4. a comment's box ticks in place"] = comment === "- [x] Reply to the reporter\n- [ ] Close the thread";

    // 6 — refused, not overwritten: edit behind the viewer's back, then tick.
    await session.eval(`(async () => { ${API}
      const current = (await api("GET", "/items/${fixture.item.id}")).body.description;
      await api("PATCH", "/items/${fixture.item.id}", { description: current + "\\n\\nEdited elsewhere." });
    })()`);
    // The viewer still shows the old text until the live update lands; tick immediately.
    await clickAt(send, `[data-task-toggle] ${LABEL}`);
    await sleep(1800);
    const stale = await session.eval(`(async () => { ${API}
      return (await api("GET", "/items/${fixture.item.id}")).body.description;
    })()`);
    checks["6. a stale tick is refused and the other edit survives"] =
      stale.endsWith("Edited elsewhere.") && stale.startsWith("Release checklist\n\n- [x] Write the notes");

    // 5 — the page, split around a radd:toc block.
    await session.navigate(`${baseUrl}/pages?pageId=${fixture.page.number}`, 3500);
    const pageLabels = await session.eval(`document.querySelectorAll("[data-page-body] ${LABEL}").length`);
    await session.eval(`(() => {
      const labels = document.querySelectorAll("[data-page-body] ${LABEL}");
      labels[labels.length - 1].setAttribute("data-proof-page-target", "");
    })()`);
    await clickAt(send, "[data-proof-page-target]");
    await sleep(1800);
    const page = await session.eval(`(async () => { ${API} return (await api("GET", "/pages/${fixture.page.id}")).body; })()`);
    context.page = { labels: pageLabels, version: page.version, body: page.body };
    checks["5a. ticking the box after a radd block flips THAT line"] =
      pageLabels === 2 && page.body.includes("- [ ] Before the block") && page.body.includes("- [x] After the block");
    checks["5b. …as a versioned save"] = page.version === fixture.page.version + 1;
    await session.screenshot(resolve(SHOTS, "page.png"));
  } finally {
    if (fixture) {
      context.cleanup = await session.eval(`(async () => { ${API}
        return {
          page: (await api("DELETE", "/pages/${fixture.page.id}?hard=true")).status,
          space: (await api("DELETE", "/page-spaces/${fixture.space.id}")).status,
          project: (await api("DELETE", "/projects/${fixture.project.id}")).status,
        };
      })()`).catch((error) => String(error));
    }
    await close();
  }
  context.shots = SHOTS;
  process.exit(report(checks, context) ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

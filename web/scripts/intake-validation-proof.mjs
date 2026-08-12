/**
 * Spec 119: the Validate flow, measured in a browser.
 *
 * `tsc -b` and `vite build` cannot see any of what this checks. A findings panel
 * that renders off-screen, a field highlight that never reaches the control, a
 * "Create anyway" button offered where the server would refuse it, or a
 * required-mode panel whose text sits under 4.5:1 — all of those compile.
 *
 * NO MODEL IS INVOLVED. The graph is deterministic: a `filter.slq` on the TITLE
 * gates a `validation.fail`, so the same New Item modal produces the fail state
 * for one title and the pass state for another. The `ai.validate` node is
 * exercised by the server suite with the client mocked; a proof that needed a
 * live provider would be a proof that fails when the provider is busy.
 *
 * Asserts, in both themes:
 *   - the button reads "Validate & create" where a graph governs, and plain
 *     "Create item" where none does;
 *   - a failing submission renders the findings panel with the check's message,
 *     and highlights the exact control the finding names;
 *   - the panel is ON SCREEN and inside the modal (a panel appended to the body
 *     at x:-110 was RADD-762's whole lesson);
 *   - "Create anyway" is offered under ADVISORY and absent under REQUIRED;
 *   - a passing submission closes the modal and creates the item;
 *   - the panel's text clears 4.5:1 against what it actually sits on.
 *
 * Usage: node scripts/intake-validation-proof.mjs [--base http://127.0.0.1:8119]
 */
import { writeFileSync } from "node:fs";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const args = process.argv.slice(2);
const baseUrl = args.includes("--base") ? args[args.indexOf("--base") + 1] : "http://127.0.0.1:8119";
const email = process.env.RADD_PROOF_EMAIL ?? "proof@radd.local";
const password = process.env.RADD_PROOF_PASSWORD ?? "proof-119";

const CHECK_MESSAGE = "A crash report needs steps to reproduce and what you expected.";
const { session, close } = await openBrowser({ port: 9351, profile: "/tmp/radd-intake-validation-proof" });

const api = (method, path, body) =>
  `(async()=>{const r=await fetch("/api/v1${path}",{method:${JSON.stringify(method)},` +
  `credentials:"include",headers:{"Content-Type":"application/json"}` +
  (body === undefined ? "" : `,body:JSON.stringify(${JSON.stringify(body)})`) +
  `});return {status:r.status, body: await r.text()};})()`;

const parsed = (result) => (result.status < 300 ? JSON.parse(result.body) : null);

await session.navigate(baseUrl, 1500);
const loginStatus = await session.login(baseUrl, email, password);

// Headless Chrome reports (hover: none) at baseline, and Tailwind gates every
// hover: utility on @media (hover: hover) — so a proof without the flag
// describes un-hovered chrome and calls it a bug.
const hoverCapable = await session.hoverCapable();

// --- the world ---------------------------------------------------------------

const suffix = Date.now().toString(36).slice(-4).toUpperCase();
const governed = parsed(
  await session.eval(api("POST", "/projects", { key: `VG${suffix}`, name: "Validated intake" })),
);
const ungoverned = parsed(
  await session.eval(api("POST", "/projects", { key: `VU${suffix}`, name: "Plain intake" })),
);

/** A graph whose check fires only for a title containing "crash" — the same
 * modal then produces both states, with no model and no second fixture.
 *
 * The TITLE rather than the priority, because the priority control is the house
 * `SelectField`, not a native `<select>`, and driving a custom listbox from a
 * probe would be testing the harness. The title is a plain input, so what the
 * proof types is what the server receives.
 */
const graphFor = (mode) => ({
  name: `intake checks ${mode} ${suffix}`,
  nodes: [
    {
      id: "trg",
      kind: "trigger",
      type: "trigger.event",
      params: {
        event: "validate",
        targets: [{ kind: "project", id: governed.id }],
        mode,
      },
    },
    { id: "f", kind: "filter", type: "filter.slq", params: { slq: 'title ~ "crash"' } },
    {
      id: "chk",
      kind: "action",
      type: "validation.fail",
      params: { message: CHECK_MESSAGE, field: "description" },
    },
  ],
  edges: [
    { source: "trg", port: "out", target: "f" },
    { source: "f", port: "matched", target: "chk" },
  ],
});

const advisory = parsed(await session.eval(api("POST", "/automations", graphFor("advisory"))));

// --- probes -------------------------------------------------------------------

const FILL = (title) => `(() => {
  const setNative = (node, value) => {
    // React dedupes by its own value tracker, so the value must be set through
    // the PROTOTYPE setter (bypassing React's instance override) for the change
    // event to be seen as a change at all.
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(node, value);
    node.dispatchEvent(new Event("input", { bubbles: true }));
    node.dispatchEvent(new Event("change", { bubbles: true }));
  };
  const dialog = document.querySelector("[role=dialog]");
  if (!dialog) return { ok: false, why: "no dialog" };
  const titleInput = [...dialog.querySelectorAll("input")]
    .find((i) => /short, imperative/i.test(i.placeholder || ""));
  if (!titleInput) return { ok: false, why: "no title input" };
  setNative(titleInput, ${JSON.stringify(title)});
  return { ok: true };
})()`;

const SUBMIT_LABEL = `(() => {
  const dialog = document.querySelector("[role=dialog]");
  if (!dialog) return null;
  const button = [...dialog.querySelectorAll("button[type=submit]")].pop();
  return button ? (button.textContent || "").trim() : null;
})()`;

const PRESS_SUBMIT = `(() => {
  const dialog = document.querySelector("[role=dialog]");
  const button = dialog && [...dialog.querySelectorAll("button[type=submit]")].pop();
  if (!button) return false;
  button.click();
  return true;
})()`;

const MEASURE = `(() => {
  const panel = document.querySelector("[data-findings-panel]");
  const dialog = document.querySelector("[role=dialog]");
  const anyway = dialog
    ? [...dialog.querySelectorAll("button")]
        .some((b) => /create anyway/i.test(b.textContent || ""))
    : false;
  if (!panel) return { present: false, anyway, dialogOpen: Boolean(dialog) };
  const rect = panel.getBoundingClientRect();
  const style = getComputedStyle(panel);
  const item = panel.querySelector("li");
  const itemStyle = item ? getComputedStyle(item) : null;
  // Walk to the first OPAQUE ancestor. The panel's own wash is a 5%-alpha tint
  // and several tokens compute as oklab(), so "has a background" is not the
  // test — anything translucent lets the ground below it through, and treating
  // a 5% tint as the backdrop is how a light-theme run once reported 1.49:1
  // for text that is actually near-black on white. The ground is what the eye
  // sees; the tint over it moves the ratio by a rounding error.
  let behind = panel, backdrop = "rgb(255, 255, 255)";
  while (behind) {
    const value = getComputedStyle(behind).backgroundColor;
    if (/^rgb\\([^)]*\\)$/.test(value || "")) { backdrop = value; break; }
    behind = behind.parentElement;
  }
  const field = document.querySelector("[data-finding-field]");
  return {
    present: true,
    anyway,
    dialogOpen: Boolean(dialog),
    blocking: panel.getAttribute("data-blocking"),
    text: (panel.textContent || "").trim(),
    rect: { x: rect.x, y: rect.y, w: rect.width, h: rect.height },
    // WITHIN THE VIEWPORT, not merely "has positive coordinates". The first
    // version of this check tested x/y >= 0 and passed while the panel sat
    // several hundred pixels below the fold of a long modal — present, sized,
    // and never seen. The screenshot is what caught it.
    onScreen:
      rect.width > 100 &&
      rect.x >= 0 &&
      rect.x < innerWidth &&
      rect.y >= 0 &&
      rect.y < innerHeight,
    insideDialog: Boolean(dialog && dialog.contains(panel)),
    role: panel.getAttribute("role"),
    itemColor: itemStyle ? itemStyle.color : null,
    backdrop,
    //: The panel's own translucent wash, reported so the ratio below is
    //: readable as "text on the ground, tinted" rather than as a mystery.
    wash: style.backgroundColor,
    fieldNamed: field ? field.getAttribute("data-finding-field") : null,
    // The finding also has to reach the CONTROL it names: the description
    // finding renders inside the description block, not only in the panel.
    highlightedDescription: [
      ...document.querySelectorAll("[data-field=description] p"),
    ].some((p) => (p.textContent || "").includes(${JSON.stringify(CHECK_MESSAGE)})),
  };
})()`;

const contrast = (a, b) => {
  const channel = (value) => {
    const c = value / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const parse = (css) => (css.match(/[\d.]+/g) || []).slice(0, 3).map(Number);
  const luminance = (css) => {
    const [r, g, bl] = parse(css);
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(bl);
  };
  const [l1, l2] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
};

/** Open the project, open the modal, fill it, press the button, measure. */
async function run({ projectKey, title, light, shot }) {
  await session.navigate(`${baseUrl}/p/${projectKey}/issues`, 1200);
  await session.eval(
    light
      ? `document.documentElement.classList.add("light")`
      : `document.documentElement.classList.remove("light")`,
  );
  // Real mouse events, not `element.click()` — the pins-bar button opens a
  // MENU when more than one project is creatable, and only hit-tested input
  // reproduces that. RADD-742's lesson.
  await session.click("button", (text) => /^\s*new item\s*$/i.test(text));
  await sleep(500);
  const menuOpen = await session.eval(
    `[...document.querySelectorAll("button[role=menuitem]")].some((b) => (b.textContent || "").startsWith(${JSON.stringify(projectKey)}))`,
  );
  if (menuOpen) {
    // `clickAt` serialises the matcher with `.toString()` and evaluates it IN
    // THE PAGE, so a closure over `projectKey` arrives as an undefined
    // reference. Building it from source bakes the value in.
    const startsWithKey = new Function(
      "text",
      `return text.trim().startsWith(${JSON.stringify(projectKey)})`,
    );
    await session.click("button[role=menuitem]", startsWithKey);
  }
  await sleep(900);
  const filled = await session.eval(FILL(title));
  const readback = await session.eval(`(() => {
    const dialog = document.querySelector("[role=dialog]");
    if (!dialog) return null;
    const t = [...dialog.querySelectorAll("input")]
      .find((i) => /short, imperative/i.test(i.placeholder || ""));
    return { title: t ? t.value : null };
  })()`);
  const label = await session.eval(SUBMIT_LABEL);
  await session.eval(PRESS_SUBMIT);
  await sleep(1400);
  const measured = await session.eval(MEASURE);
  // A picture as well as the numbers: the measurements say the panel is on
  // screen and legible, and the shot is what someone can look at when they
  // disagree.
  if (shot) {
    const { data } = await session.send("Page.captureScreenshot", { format: "png" });
    writeFileSync(shot, Buffer.from(data, "base64"));
  }
  return { filled, readback, label, measured };
}

const advisoryDark = await run({
  projectKey: governed.key,
  title: "it crashes on save",
  light: false,
  shot: "/tmp/radd-s119-findings-dark.png",
});

/**
 * THE VERDICT WINS OVER THE CACHED CONTEXT (RADD-1060).
 *
 * The modal asks `GET /items/validate/context` once and caches it for a minute.
 * Flipping the binding to REQUIRED while the modal is open and pressing again
 * is the case where the two answers disagree: the cached context still says
 * advisory, the response says required. Rendering the mode from the context
 * read put an advisory panel — and a "Create anyway" button the server would
 * refuse with a 409 — under a required verdict.
 *
 * Done here, in the page left open by the run above, and put back afterwards so
 * the rest of the sequence sees the fixture it expects.
 */
await session.eval(api("PATCH", `/automations/${advisory.id}`, graphFor("required")));
await session.eval(PRESS_SUBMIT);
await sleep(1400);
const staleContext = await session.eval(MEASURE);
await session.eval(api("PATCH", `/automations/${advisory.id}`, graphFor("advisory")));

const advisoryLight = await run({
  projectKey: governed.key,
  title: "it crashes on export",
  light: true,
  shot: "/tmp/radd-s119-findings-light.png",
});

// The PASS state: same modal, same graph, a priority the filter excludes.
const passing = await run({
  projectKey: governed.key,
  title: "a tidy request",
  light: false,
});

// An UNGOVERNED project must be untouched — the plain Create button.
const plain = await run({
  projectKey: ungoverned.key,
  title: "no checks here",
  light: false,
});

// REQUIRED mode: same fixture, stricter binding. "Create anyway" must be gone.
await session.eval(api("PATCH", `/automations/${advisory.id}`, graphFor("required")));
const required = await run({
  projectKey: governed.key,
  title: "still crashes",
  light: false,
  shot: "/tmp/radd-s119-findings-required.png",
});

/**
 * MIXED GOVERNANCE — the case a client cannot compute for itself.
 *
 * Two graphs govern the same draft: one REQUIRED whose check sits behind a
 * filter this draft does not match, one ADVISORY that trips. The strictest mode
 * is "required" — something required IS watching — and nothing required
 * objected, so the server would honour `commit: always`. A client gating the
 * affordance on `mode === "required"` hides a button the server accepts; one
 * gating it on `blocking` matches exactly. `POST /items` accepts this draft too,
 * which is the disagreement the flag closes.
 */
await session.eval(api("PATCH", `/automations/${advisory.id}`, graphFor("advisory")));
await session.eval(
  api("POST", "/automations", {
    name: `unmatched required ${suffix}`,
    nodes: [
      {
        id: "trg",
        kind: "trigger",
        type: "trigger.event",
        params: {
          event: "validate",
          targets: [{ kind: "project", id: governed.id }],
          mode: "required",
        },
      },
      // A condition no draft in this proof meets, so this graph governs
      // everything and refuses nothing.
      { id: "f", kind: "filter", type: "filter.slq", params: { slq: 'title ~ "zzzznever"' } },
      {
        id: "chk",
        kind: "action",
        type: "validation.fail",
        params: { message: "An outage report needs a severity." },
      },
    ],
    edges: [
      { source: "trg", port: "out", target: "f" },
      { source: "f", port: "matched", target: "chk" },
    ],
  }),
);
const mixed = await run({
  projectKey: governed.key,
  title: "it crashes on open",
  light: false,
  shot: "/tmp/radd-s119-findings-mixed.png",
});

const itemsAfter = parsed(
  await session.eval(api("GET", `/items?project_id=${governed.id}`)),
);

const panelContrast = advisoryDark.measured.present
  ? contrast(advisoryDark.measured.itemColor, advisoryDark.measured.backdrop)
  : 0;
const panelContrastLight = advisoryLight.measured.present
  ? contrast(advisoryLight.measured.itemColor, advisoryLight.measured.backdrop)
  : 0;

const failed = report(
  {
    "logged in": loginStatus === 204,
    "hover is capable (the flag reached this browser)": hoverCapable === true,
    "fixtures created": Boolean(governed && ungoverned && advisory),

    "governed: the button says Validate": /validate/i.test(advisoryDark.label || ""),
    "ungoverned: the button says Create item": /create item/i.test(plain.label || ""),

    "fail state: the findings panel is rendered": advisoryDark.measured.present === true,
    "fail state: it carries the check's own message":
      (advisoryDark.measured.text || "").includes(CHECK_MESSAGE),
    "fail state: the panel is ON SCREEN, not painted off the left edge":
      advisoryDark.measured.onScreen === true,
    "fail state: it takes layout INSIDE the modal": advisoryDark.measured.insideDialog === true,
    "fail state: it is a live region": advisoryDark.measured.role === "status",
    "fail state: the finding names the control it is about":
      advisoryDark.measured.fieldNamed === "description",
    "fail state: the control ITSELF is annotated, not only the panel":
      advisoryDark.measured.highlightedDescription === true,
    "fail state: the modal stays open so it can be fixed":
      advisoryDark.measured.dialogOpen === true,
    "fail state: nothing was created": (itemsAfter || []).every(
      (item) => item.title !== "it crashes on save",
    ),

    "advisory: Create anyway is offered": advisoryDark.measured.anyway === true,
    "required: Create anyway is NOT offered": required.measured.anyway === false,
    "required: the panel says so": required.measured.blocking === "true",

    // The verdict beats the cached context read: the binding became required
    // while this modal was open, and the panel follows the ANSWER, not the
    // minute-old lookup that decided the button's wording.
    "stale context: the panel switches to a refusal": staleContext.blocking === "true",
    "stale context: Create anyway is withdrawn": staleContext.anyway === false,
    "stale context: the findings are still listed":
      (staleContext.text || "").includes(CHECK_MESSAGE),

    // Mixed governance: required watching, advisory tripping. The affordance
    // follows the server's `blocking`, not the aggregated mode — which is
    // "required" here, and would have hidden a button the server honours.
    "mixed: the panel renders": mixed.measured.present === true,
    "mixed: an advisory finding under a required graph does NOT refuse":
      mixed.measured.blocking === "false",
    "mixed: Create anyway is offered, as the server would honour it":
      mixed.measured.anyway === true,

    "pass state: no findings panel": passing.measured.present === false,
    "pass state: the modal closed": passing.measured.dialogOpen === false,
    "pass state: the item exists": (itemsAfter || []).some(
      (item) => item.title === "a tidy request",
    ),

    "light theme: the panel renders too": advisoryLight.measured.present === true,
    "dark: finding text clears 4.5:1": panelContrast >= 4.5,
    "light: finding text clears 4.5:1": panelContrastLight >= 4.5,

    // Plugin UI remotes are built by `build-all.mjs` into the image; a bare
    // `vite build` leaves them absent and the loader quarantines each with a
    // console error. That is this harness, not the page under test.
    "no console errors": session.consoleErrors.filter(
      (line) => !/plugin UI .* failed to load \(quarantined\)/.test(line),
    ).length === 0,
  },
  {
    label: { governed: advisoryDark.label, ungoverned: plain.label },
    advisoryDark: advisoryDark.measured,
    readback: { fail: advisoryDark.readback, pass: passing.readback },
    advisoryLight: {
      present: advisoryLight.measured.present,
      itemColor: advisoryLight.measured.itemColor,
      backdrop: advisoryLight.measured.backdrop,
      wash: advisoryLight.measured.wash,
    },
    required: { anyway: required.measured.anyway, blocking: required.measured.blocking },
    staleContext: { blocking: staleContext.blocking, anyway: staleContext.anyway },
    mixed: { blocking: mixed.measured.blocking, anyway: mixed.measured.anyway },
    passing: { present: passing.measured.present, dialogOpen: passing.measured.dialogOpen },
    contrast: { dark: Number(panelContrast.toFixed(2)), light: Number(panelContrastLight.toFixed(2)) },
    consoleErrors: session.consoleErrors
      .filter((line) => !/plugin UI .* failed to load \(quarantined\)/.test(line))
      .slice(0, 5),
  },
);

close();
process.exit(failed ? 1 : 0);

/**
 * RADD-1064: the `ai.validate` node as the GRAPH BUILDER draws it.
 *
 * Two bugs the owner hit building his first validation rule, both invisible to
 * `tsc -b` and `vite build`, and both about the node's own configuration surface
 * rather than about what the node does:
 *
 *   1. PORTS. The canvas special-cased `ai.classify` and otherwise fell back to
 *      the KIND's table, so this GATE was drawn with TRUE/FALSE handles. Every
 *      edge dragged off one named a port the engine never emits — a branch that
 *      silently carries nothing, and a graph the server refuses on save.
 *   2. THE INCLUDE FORM. The generated JSON-Schema form had no case for an
 *      object of booleans, so "What the model sees" rendered as a free-text
 *      input. Typing `{{title}}` into it stores a STRING where the node reads a
 *      mapping — which the write path accepts and the run then catches as "the
 *      provider is unavailable". A check that checks nothing, blaming the model
 *      server.
 *
 * So this proof reads the handles and the checkboxes out of the real editor.
 * NO MODEL IS INVOLVED: nothing here runs the node, only configures it.
 *
 * Asserts:
 *   - the catalog DECLARES this node's ports and declares `ai.classify`'s as
 *     dynamic (an empty list is the positive statement, not a gap);
 *   - a freshly dropped node draws pass/fail/unavailable — as labels AND as
 *     React Flow handle ids, which is what an edge actually carries;
 *   - `include` renders as four checkboxes with the schema's own defaults, and
 *     as no text input;
 *   - a toggled checkbox saves as an OBJECT and survives a reload;
 *   - a node holding the string casualty renders the defaults instead of it.
 *
 * RADD-1074 extends it with what the canvas says about a FINDING. In a graph
 * whose trigger is `validate`, a finding is not a branch — it is the intake
 * verdict, delivered to whoever submitted. The empty handle under `fail`
 * therefore reads as an unfinished graph when it is a finished one, and people
 * went looking for the action that sends the feedback. So:
 *   - the finding-producing ports carry a "feedback to submitter" note;
 *   - an UNWIRED one is drawn as a deliberate cap, a wired one is not;
 *   - none of it appears on a graph that is not validate-triggered, where the
 *     same node really is a plain pass/fail router;
 *   - and it reads in both themes.
 *
 * Usage: node scripts/ai-validate-node-proof.mjs [--base http://127.0.0.1:8124]
 */
import { writeFileSync } from "node:fs";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const args = process.argv.slice(2);
const baseUrl = args.includes("--base") ? args[args.indexOf("--base") + 1] : "http://127.0.0.1:8124";
const email = process.env.RADD_PROOF_EMAIL ?? "proof@radd.local";
const password = process.env.RADD_PROOF_PASSWORD ?? "proof-1064";

const NODE_TYPE = "ai.validate";
const EXPECTED_PORTS = ["pass", "fail", "unavailable"];
const INCLUDE_KEYS = ["fields", "description", "comments", "worklogs"];
const BAR = "A bug report must name the version and the steps to reproduce.";

const { session, close } = await openBrowser({ port: 9353, profile: "/tmp/radd-ai-validate-proof" });

const api = (method, path, body) =>
  `(async()=>{const r=await fetch("/api/v1${path}",{method:${JSON.stringify(method)},` +
  `credentials:"include",headers:{"Content-Type":"application/json"}` +
  (body === undefined ? "" : `,body:JSON.stringify(${JSON.stringify(body)})`) +
  `});return {status:r.status, body: await r.text()};})()`;

const parsed = (result) => (result.status < 300 ? JSON.parse(result.body) : null);

await session.navigate(baseUrl, 1500);
const loginStatus = await session.login(baseUrl, email, password);
// Headless Chrome reports (hover: none) at baseline and Tailwind gates every
// hover: utility on it — a proof without the flag describes un-hovered chrome.
const hoverCapable = await session.hoverCapable();

// --- what the SERVER says the node emits --------------------------------------

const catalog = parsed(await session.eval(api("GET", "/automations/catalog")));
const contributed = Object.fromEntries(
  (catalog?.contributed_nodes ?? []).map((node) => [node.key, node]),
);

// --- the world ----------------------------------------------------------------

const suffix = Date.now().toString(36).slice(-4).toUpperCase();
const ruleName = `validate builder ${suffix}`;
const rule = parsed(
  await session.eval(
    api("POST", "/automations", {
      name: ruleName,
      enabled: false,
      orientation: "vertical",
      nodes: [
        { id: "trg", kind: "trigger", type: "trigger.event", params: { event: "manual" } },
      ],
      edges: [],
    }),
  ),
);

// --- probes -------------------------------------------------------------------

const OPEN_RULE = `(() => {
  const button = document.querySelector('[aria-label="Edit ${ruleName}"]');
  if (button) button.click();
  return Boolean(button);
})()`;

const SEARCH_NODES = (text) => `(() => {
  const input = document.querySelector('[data-node-panel] input[aria-label="Search nodes"]');
  if (!input) return false;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  setter.call(input, ${JSON.stringify(text)});
  input.dispatchEvent(new Event("input", { bubbles: true }));
  return true;
})()`;

const ADD_NODE = `(() => {
  const row = [...document.querySelectorAll("[data-node-panel] li button")]
    .find((b) => /ai check/i.test(b.textContent || ""));
  if (row) row.click();
  return Boolean(row);
})()`;

/** The handles the canvas actually drew for the node, by LABEL and by the
 * handle id an edge would carry. Both, because they are drawn from the same
 * array and a proof that only read the labels would pass on a node whose
 * wireable ids were still the kind's. */
const CANVAS_PORTS = `(() => {
  const card = [...document.querySelectorAll("[data-node-id]")]
    .find((el) => (el.innerText || "").includes(${JSON.stringify(NODE_TYPE)}));
  if (!card) return { found: false };
  const rect = card.getBoundingClientRect();
  return {
    found: true,
    labels: [...card.querySelectorAll("[data-port-label]")].map((el) =>
      el.getAttribute("data-port-label"),
    ),
    // React Flow stamps the handle id it will hand to onConnect.
    handles: [...card.querySelectorAll(".react-flow__handle-bottom, .react-flow__handle-right")]
      .map((el) => el.getAttribute("data-handleid")),
    // Drawn where someone can see it, not merely present in the DOM.
    onScreen: rect.width > 50 && rect.y >= 0 && rect.y < innerHeight,
  };
})()`;

/** The include group as rendered, plus whether the old free-text input is gone. */
const INCLUDE_FORM = `(() => {
  const boxes = [...document.querySelectorAll("[data-schema-check]")];
  const group = document.querySelector("[data-schema-group]");
  const fields = document.querySelector("[data-schema-fields]");
  const textInputs = fields
    ? [...fields.querySelectorAll("input")]
        .filter((i) => i.type !== "checkbox")
        .map((i) => {
          const label = i.id ? document.querySelector('label[for="' + i.id + '"]') : null;
          return (label ? label.textContent : "").trim();
        })
    : [];
  return {
    keys: boxes.map((b) => b.getAttribute("data-schema-check")),
    checked: Object.fromEntries(boxes.map((b) => [b.getAttribute("data-schema-check"), b.checked])),
    groupLabel: group ? (group.getAttribute("data-schema-group") || "") : null,
    // The bug's fingerprint: a text field standing where the object belongs.
    textInputLabels: textInputs,
  };
})()`;

const TOGGLE = (key) => `(() => {
  const box = document.querySelector('[data-schema-check="${key}"]');
  if (!box) return false;
  box.click();
  return true;
})()`;

const FILL_BAR = `(() => {
  const label = [...document.querySelectorAll("label")]
    .find((l) => /quality bar/i.test(l.textContent || ""));
  const input = label && document.getElementById(label.htmlFor);
  if (!input) return false;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  setter.call(input, ${JSON.stringify(BAR)});
  input.dispatchEvent(new Event("input", { bubbles: true }));
  return true;
})()`;

const SAVE = `(() => {
  const button = [...document.querySelectorAll("button[type=submit]")]
    .find((b) => /save changes|create automation/i.test(b.textContent || ""));
  if (!button) return false;
  button.click();
  return true;
})()`;

const SAVE_ERROR = `(() => {
  const text = document.body.innerText;
  const match = text.match(/Rejected on save:[^\\n]*/);
  return { rejected: match ? match[0] : null, saved: /\\bSaved\\b/.test(text) };
})()`;

/** Land on the list, open the rule, wait for the lazy canvas. */
async function openEditor() {
  await session.navigate(`${baseUrl}/settings/automations`, 2200);
  const opened = await session.eval(OPEN_RULE);
  await sleep(2500);
  return opened;
}

/** Select the check node on the canvas so the inspector renders its form.
 *
 * A REAL click through the input pipeline, not a synthesised MouseEvent:
 * React Flow's pointer handler reads `event.view.document`, and a hand-built
 * event carries `view: null` — the resulting TypeError looks exactly like a
 * product bug in the console. RADD-742's lesson, from the other end. */
const selectNode = () =>
  session.click("[data-node-id]", (text) => text.includes("ai.validate"));

// --- 1. drop the node ---------------------------------------------------------

const opened = await openEditor();
await session.eval(SEARCH_NODES("ai check"));
await sleep(700);
const added = await session.eval(ADD_NODE);
await sleep(1600);

const freshPorts = await session.eval(CANVAS_PORTS);
const freshInclude = await session.eval(INCLUDE_FORM);

// --- 2. configure and save ----------------------------------------------------

await session.eval(FILL_BAR);
await sleep(300);
const toggled = await session.eval(TOGGLE("comments"));
await sleep(400);
const afterToggle = await session.eval(INCLUDE_FORM);
const shot = await session.send("Page.captureScreenshot", { format: "png" });
writeFileSync("/tmp/radd-1064-builder.png", Buffer.from(shot.data, "base64"));
await session.eval(SAVE);
await sleep(1600);
const saveState = await session.eval(SAVE_ERROR);

// The LIST, not the automation: there is no `GET /automations/{id}` — the SPA
// reads the list and filters it, so this proof reads what the SPA reads.
const storedRules = parsed(await session.eval(api("GET", "/automations")));
const stored = (storedRules ?? []).find((entry) => entry.id === rule?.id);
const storedNode = (stored?.nodes ?? []).find((node) => node.type === NODE_TYPE);
const storedInclude = storedNode?.params?.include;

// --- 3. it survives a reload --------------------------------------------------

await openEditor();
await selectNode();
await sleep(800);
const reloadedPorts = await session.eval(CANVAS_PORTS);
const reloadedInclude = await session.eval(INCLUDE_FORM);

// --- 4. the casualty renders as the defaults, not as itself -------------------
//
// A node saved while the form was a text box holds `include: "{{title}}"`. The
// form reads a non-object as the schema's defaults, so the person sees what the
// node will actually do and the next click writes the right shape back.

await session.eval(
  api("PATCH", `/automations/${rule?.id}`, {
    nodes: (stored?.nodes ?? []).map((node) =>
      node.type === NODE_TYPE
        ? { ...node, params: { ...node.params, include: "{{title}}" } }
        : node,
    ),
    edges: stored?.edges ?? [],
  }),
);
await openEditor();
await selectNode();
await sleep(800);
const healedInclude = await session.eval(INCLUDE_FORM);

// --- 5. what a VALIDATION graph says about its findings (RADD-1074) -----------

const project = parsed(
  await session.eval(
    api("POST", "/projects", { key: `VF${suffix}`, name: `Validate ${suffix}` }),
  ),
);

/** Two checks: one whose fail port is WIRED onward, one whose is not — the
 * difference is the whole assertion about the cap. */
const validationRuleName = `validation feedback ${suffix}`;
const validationRule = parsed(
  await session.eval(
    api("POST", "/automations", {
      name: validationRuleName,
      enabled: false,
      orientation: "vertical",
      nodes: [
        {
          id: "trg",
          kind: "trigger",
          type: "trigger.event",
          params: {
            event: "validate",
            mode: "advisory",
            targets: [{ kind: "project", id: project?.id }],
          },
        },
        {
          id: "check",
          kind: "gate",
          type: NODE_TYPE,
          params: { prompt: BAR },
        },
        {
          id: "say",
          kind: "action",
          type: "validation.fail",
          params: { message: "Please name the version you saw this on.", field: "description" },
        },
      ],
      edges: [
        { source: "trg", port: "out", target: "check" },
        { source: "check", port: "fail", target: "say" },
      ],
    }),
  ),
);

/** The badge, the caps, and the inspector line, read off the real canvas. */
const FEEDBACK = `(() => {
  const cards = [...document.querySelectorAll("[data-node-id]")];
  const of = (id) => cards.find((card) => card.getAttribute("data-node-id") === id);
  const read = (card) => {
    if (!card) return null;
    const note = card.querySelector("[data-feedback-note]");
    const caps = [...card.querySelectorAll("[data-port-cap]")].map((el) =>
      el.getAttribute("data-port-cap"),
    );
    const rect = note ? note.getBoundingClientRect() : null;
    return {
      note: note ? note.getAttribute("data-feedback-note") : null,
      text: note ? note.textContent.trim() : "",
      color: note ? getComputedStyle(note).color : null,
      readable: Boolean(rect && rect.width > 40 && rect.height > 5),
      caps,
      capSize: [...card.querySelectorAll("[data-port-cap]")].map(
        (el) => el.getBoundingClientRect().width,
      ),
      plainPortSize: [...card.querySelectorAll(".react-flow__handle-bottom")]
        .filter((el) => !el.hasAttribute("data-port-cap"))
        .map((el) => el.getBoundingClientRect().width),
    };
  };
  return { check: read(of("check")), say: read(of("say")) };
})()`;

/** Raw text, normalised in NODE rather than in the page: a regex literal inside
 * a page-eval template string loses its backslashes, so `/\s+/g` arrives as
 * `/s+/g` and quietly deletes every "s" in the answer. */
const INSPECTOR_NOTE = `(() => {
  const note = document.querySelector("p[data-feedback-note]");
  return note ? note.textContent : null;
})()`;

async function openValidationEditor() {
  await session.navigate(`${baseUrl}/settings/automations`, 2200);
  await session.eval(`(() => {
    const button = document.querySelector('[aria-label="Edit ${validationRuleName}"]');
    if (button) button.click();
    return Boolean(button);
  })()`);
  await sleep(2600);
}

await openValidationEditor();
const feedbackThemes = {};
for (const theme of ["dark", "light"]) {
  await session.eval(
    `document.documentElement.classList.toggle("light", ${JSON.stringify(theme)} === "light"); "ok"`,
  );
  await sleep(400);
  feedbackThemes[theme] = await session.eval(FEEDBACK);
  const shot = await session.send("Page.captureScreenshot", { format: "png" });
  writeFileSync(`/tmp/radd-1074-feedback-${theme}.png`, Buffer.from(shot.data, "base64"));
}
await session.eval(`document.documentElement.classList.remove("light"); "ok"`);
await session.click("[data-node-id]", new Function("text", "return text.includes('ai.validate')"));
await sleep(900);
const inspectorNote = (await session.eval(INSPECTOR_NOTE))?.replace(/\s+/g, " ").trim() ?? null;

// …and NONE of it on the manual-triggered rule from the first half, where the
// same node really is a plain pass/fail router.
await openEditor();
await sleep(600);
const manualFeedback = await session.eval(
  `[...document.querySelectorAll("[data-feedback-note], [data-port-cap]")].length`,
);

// --- teardown -----------------------------------------------------------------

if (validationRule) await session.eval(api("DELETE", `/automations/${validationRule.id}`));
if (rule) await session.eval(api("DELETE", `/automations/${rule.id}`));

/** Order MATTERS: port order decides which handle is which, and the last port is
 * the executor's fallback. */
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/** Order does NOT matter, and asserting it would be asserting Postgres.
 * A round-tripped `include` comes back key-sorted by JSONB's own rule (shortest
 * first, then bytewise) — `fields, comments, worklogs, description` — which is
 * nothing the form did and nothing anyone can see. */
const sameMap = (a, b) =>
  Boolean(a) &&
  typeof a === "object" &&
  !Array.isArray(a) &&
  JSON.stringify(Object.entries(a).sort()) === JSON.stringify(Object.entries(b).sort());

const failed = report(
  {
    "logged in": loginStatus === 204,
    "hover is capable (the flag reached this browser)": hoverCapable === true,
    "fixture created": Boolean(rule?.id),
    "the editor opened": opened === true && added === true,

    "catalog: the check DECLARES its ports": same(contributed[NODE_TYPE]?.ports, EXPECTED_PORTS),
    "catalog: the classifier declares none (its ports are its answers)": same(
      contributed["ai.classify"]?.ports,
      [],
    ),

    "canvas: the node is drawn": freshPorts.found === true && freshPorts.onScreen === true,
    "canvas: the port LABELS read pass/fail/unavailable": same(freshPorts.labels, EXPECTED_PORTS),
    "canvas: the HANDLES an edge would carry match them": same(
      freshPorts.handles,
      EXPECTED_PORTS,
    ),
    "canvas: no gate TRUE/FALSE handles remain": !(freshPorts.handles ?? []).some((id) =>
      ["true", "false"].includes(id),
    ),

    "form: include renders as four checkboxes": same(freshInclude.keys, INCLUDE_KEYS),
    "form: with the schema's own defaults": sameMap(freshInclude.checked, {
      fields: true,
      description: true,
      comments: false,
      worklogs: false,
    }),
    "form: it has the property's title as its group label":
      freshInclude.groupLabel === "What the model sees",
    "form: no free-text input stands where the object belongs": !(
      freshInclude.textInputLabels ?? []
    ).some((label) => /what the model sees/i.test(label)),

    "save: the toggle took": toggled === true && afterToggle.checked.comments === true,
    "save: accepted": saveState.saved === true && saveState.rejected === null,
    "save: it stored an OBJECT, not a string": storedInclude !== null &&
      typeof storedInclude === "object" &&
      !Array.isArray(storedInclude),
    "save: with the choice that was made": sameMap(storedInclude, {
      fields: true,
      description: true,
      comments: true,
      worklogs: false,
    }),

    "reload: the ports are still the node's own": same(reloadedPorts.labels, EXPECTED_PORTS),
    "reload: the checkboxes carry what was saved":
      reloadedInclude.checked.comments === true &&
      reloadedInclude.checked.worklogs === false,

    "casualty: a stored string renders as four checkboxes": same(healedInclude.keys, INCLUDE_KEYS),
    "casualty: showing the schema defaults, not the string": sameMap(healedInclude.checked, {
      fields: true,
      description: true,
      comments: false,
      worklogs: false,
    }),

    "validation fixture created": Boolean(validationRule?.id && project?.id),
    "feedback: the check names its finding port": feedbackThemes.dark.check?.note === "fail",
    "feedback: …and says where it goes": /feedback to submitter/i.test(
      feedbackThemes.dark.check?.text ?? "",
    ),
    "feedback: the fail node says it too": feedbackThemes.dark.say?.note === "out",
    "feedback: a WIRED finding port gets no cap": same(feedbackThemes.dark.check?.caps, []),
    "feedback: an UNWIRED one is capped": same(feedbackThemes.dark.say?.caps, ["out"]),
    "feedback: the cap is visibly bigger than a plain port": Boolean(
      (feedbackThemes.dark.say?.capSize?.[0] ?? 0) >
        Math.max(0, ...(feedbackThemes.dark.check?.plainPortSize ?? [0])),
    ),
    "feedback: the inspector says findings are delivered": /shown to whoever submitted/i.test(
      inspectorNote ?? "",
    ),
    "feedback: it reads in dark": feedbackThemes.dark.check?.readable === true,
    "feedback: it reads in light": feedbackThemes.light.check?.readable === true,
    "feedback: the theme really changed the ink":
      feedbackThemes.dark.check?.color !== feedbackThemes.light.check?.color,
    "feedback: none of it on a graph that is not validate-triggered": manualFeedback === 0,

    // Plugin UI remotes are built into the image by `build-all.mjs`; a bare
    // `vite build` leaves them absent and the loader quarantines each one. That
    // is this harness, not the page under test.
    "no console errors": session.consoleErrors.filter(
      (line) => !/plugin UI .* failed to load \(quarantined\)/.test(line),
    ).length === 0,
  },
  {
    catalogPorts: {
      "ai.validate": contributed[NODE_TYPE]?.ports,
      "ai.classify": contributed["ai.classify"]?.ports,
      "ai.classify default_ports": contributed["ai.classify"]?.default_ports,
    },
    fresh: freshPorts,
    include: { fresh: freshInclude, afterToggle: afterToggle.checked },
    stored: storedInclude,
    reloaded: { ports: reloadedPorts.labels, include: reloadedInclude.checked },
    healed: healedInclude,
    feedback: { themes: feedbackThemes, inspectorNote, manualFeedback },
    saveState,
    screenshots: [
      "/tmp/radd-1064-builder.png",
      "/tmp/radd-1074-feedback-dark.png",
      "/tmp/radd-1074-feedback-light.png",
    ],
    consoleErrors: session.consoleErrors
      .filter((line) => !/plugin UI .* failed to load \(quarantined\)/.test(line))
      .slice(0, 5),
  },
);

close();
process.exit(failed ? 1 : 0);

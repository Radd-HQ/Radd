/**
 * Spec 120: the one-call AI triage chain, built and run in the real editor.
 *
 * The claim this proves is a chain, and every link is invisible to `tsc -b`:
 * a node produces named values, the token picker offers exactly those values to
 * the nodes below it, an action's value param accepts one instead of a picked
 * value, and the dry run reports what each token became — including, on purpose,
 * one that becomes something the project does not have.
 *
 * NO LIVE MODEL. A twenty-line HTTP server in this file speaks the OpenAI
 * completions shape and answers with a fixed object, registered as an ordinary
 * AI provider row. That is deliberately at the HTTP layer rather than a
 * monkeypatch: everything between the node and the wire — the feature gate, the
 * role resolution, the JSON-Schema request, the structured extraction — is the
 * real code, and a stub any higher up would skip the parts that have actually
 * broken before.
 *
 * Asserts:
 *   - a freshly dropped `ai.generate` arrives NAMED, and the canvas shows it;
 *   - its bespoke form renders the field rows (not a JSON textarea), and a name
 *     that could never be a token is refused as it is typed;
 *   - the token picker on a DOWNSTREAM node lists that node's outputs, and lists
 *     nothing from a node it cannot be reached from;
 *   - clicking a token inserts it into the field that was last focused;
 *   - the dry run reports the produced values with the token that reads each;
 *   - an action whose token resolved to a value the project does not have shows
 *     the SKIP and the vocabulary, rather than "would apply";
 *   - both themes.
 *
 * Setup (throwaway instance — never the dev stack on :8000):
 *   cd server
 *   uv run python -c "import asyncio;from sqlalchemy.ext.asyncio import create_async_engine;\
 *     e=create_async_engine('postgresql+psycopg://radd:radd@localhost:5455/postgres',isolation_level='AUTOCOMMIT');\
 *     asyncio.run((lambda: e.connect().__aenter__())())"   # or psql: CREATE DATABASE radd_proof_s120
 *   RADD_DATABASE_URL=postgresql+psycopg://radd:radd@localhost:5455/radd_proof_s120 \
 *     RADD_BACKUP_TOOLS_OPTIONAL=true uv run alembic upgrade head
 *   RADD_DATABASE_URL=… uv run python -m radd.seed --email proof@radd.local \
 *     --password proof-1073 --name "Proof User"
 *   RADD_DATABASE_URL=… RADD_RUN_WORKERS=false \
 *     uv run uvicorn --factory radd.app:create_app --host 127.0.0.1 --port 8124
 *
 * Usage: node scripts/automations-dataflow-proof.mjs [--base http://127.0.0.1:8124]
 */
import { createServer } from "node:http";
import { writeFileSync } from "node:fs";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const args = process.argv.slice(2);
const baseUrl = args.includes("--base") ? args[args.indexOf("--base") + 1] : "http://127.0.0.1:8124";
const email = process.env.RADD_PROOF_EMAIL ?? "proof@radd.local";
const password = process.env.RADD_PROOF_PASSWORD ?? "proof-1073";

const MODEL_PORT = 8125;
const NODE_NAME = "triage";
/** What the fake model answers. `state` is deliberately a value the project does
 * NOT have — that is the skip this proof is about. */
const ANSWER = {
  text: "Customer-facing outage, escalate.",
  priority: "high",
  state: "Escalated",
};

// --- the deterministic model --------------------------------------------------

let modelCalls = 0;
let lastRequest = null;
const model = createServer((request, response) => {
  let body = "";
  request.on("data", (chunk) => (body += chunk));
  request.on("end", () => {
    modelCalls += 1;
    try {
      lastRequest = JSON.parse(body);
    } catch {
      lastRequest = null;
    }
    response.writeHead(200, { "content-type": "application/json" });
    // The OpenAI completions shape: the structured answer arrives as a JSON
    // STRING in the message content, which is what `extract_structured` parses.
    response.end(
      JSON.stringify({
        choices: [{ message: { role: "assistant", content: JSON.stringify(ANSWER) } }],
      }),
    );
  });
});
await new Promise((resolve) => model.listen(MODEL_PORT, "127.0.0.1", resolve));

const { session, close } = await openBrowser({ port: 9357, profile: "/tmp/radd-dataflow-proof" });
const done = (failed) => {
  model.close();
  close();
  process.exit(failed ? 1 : 0);
};

const api = (method, path, body) =>
  `(async()=>{const r=await fetch("/api/v1${path}",{method:${JSON.stringify(method)},` +
  `credentials:"include",headers:{"Content-Type":"application/json"}` +
  (body === undefined ? "" : `,body:JSON.stringify(${JSON.stringify(body)})`) +
  `});return {status:r.status, body: await r.text()};})()`;

const parsed = (result) => (result.status < 300 ? JSON.parse(result.body) : null);

await session.navigate(baseUrl, 1500);
const loginStatus = await session.login(baseUrl, email, password);
const hoverCapable = await session.hoverCapable();

// --- the world ----------------------------------------------------------------

const suffix = Date.now().toString(36).slice(-4).toUpperCase();

const provider = parsed(
  await session.eval(
    api("POST", "/ai/providers", {
      name: `fake ${suffix}`,
      wire_shape: "openai",
      base_url: `http://127.0.0.1:${MODEL_PORT}/v1`,
      default_model: "fake-1",
    }),
  ),
);
const roleSet = await session.eval(
  api("PUT", "/ai/roles/chat", { provider_id: provider?.id, model: "" }),
);

const project = parsed(
  await session.eval(
    api("POST", "/projects", { key: `DF${suffix}`, name: `Dataflow ${suffix}` }),
  ),
);
const item = parsed(
  await session.eval(
    api("POST", "/items", {
      project_id: project?.id,
      title: "Checkout is down for every customer",
      description: "Since the 14:00 deploy the payment page 500s for everyone.",
    }),
  ),
);
const states = parsed(await session.eval(api("GET", `/states?project_id=${project?.id}`)));
const stateNames = (states ?? []).map((state) => state.name);

const ruleName = `triage chain ${suffix}`;
const rule = parsed(
  await session.eval(
    api("POST", "/automations", {
      name: ruleName,
      enabled: false,
      orientation: "vertical",
      nodes: [{ id: "trg", kind: "trigger", type: "trigger.event", params: { event: "manual" } }],
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

const ADD_NODE = (label) => `(() => {
  const row = [...document.querySelectorAll("[data-node-panel] li button")]
    .find((b) => new RegExp(${JSON.stringify(label)}, "i").test(b.textContent || ""));
  if (row) row.click();
  return Boolean(row);
})()`;

/** The name the inspector shows for the selected node, plus whether it flagged
 * an error. */
const NAME_FIELD = `(() => {
  const label = [...document.querySelectorAll("label")]
    .find((l) => /name \\(for tokens\\)/i.test(l.textContent || ""));
  const input = label && document.getElementById(label.htmlFor);
  if (!input) return { present: false };
  const described = input.getAttribute("aria-describedby");
  return {
    present: true,
    value: input.value,
    invalid: input.getAttribute("aria-invalid") === "true",
    message: described ? (document.getElementById(described)?.textContent || "") : "",
  };
})()`;

const SET_FIELD = (labelPattern, value) => `(() => {
  const label = [...document.querySelectorAll("label")]
    .find((l) => new RegExp(${JSON.stringify(labelPattern)}, "i").test(l.textContent || ""));
  const input = label && document.getElementById(label.htmlFor);
  if (!input) return false;
  const proto = input.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
  setter.call(input, ${JSON.stringify(value)});
  input.dispatchEvent(new Event("input", { bubbles: true }));
  return true;
})()`;

/** The generate form's own rows — the shape SchemaFields cannot render. */
const GENERATE_FORM = `(() => {
  const rows = [...document.querySelectorAll("[data-generate-field]")];
  const fields = document.querySelector("[data-schema-fields]");
  return {
    rows: rows.length,
    hasFieldsTextInput: fields
      ? [...fields.querySelectorAll("input")].some((i) => {
          const label = i.id ? document.querySelector('label[for="' + i.id + '"]') : null;
          return /values to produce/i.test(label ? label.textContent : "");
        })
      : false,
    addButton: Boolean(
      [...document.querySelectorAll("button")].find((b) => /add a value/i.test(b.textContent || "")),
    ),
  };
})()`;

const ADD_VALUE_ROW = `(() => {
  const button = [...document.querySelectorAll("button")]
    .find((b) => /add a value/i.test(b.textContent || ""));
  if (!button) return false;
  button.click();
  return true;
})()`;

const NAME_VALUE_ROW = (index, name) => `(() => {
  const row = document.querySelector('[data-generate-field="${index}"]');
  if (!row) return false;
  const input = row.querySelector("input");
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  setter.call(input, ${JSON.stringify(name)});
  input.dispatchEvent(new Event("input", { bubbles: true }));
  return true;
})()`;

/** The kit's Select is a BUTTON plus a listbox, not a native `<select>` — so a
 * value setter does nothing to it. Open it, then click the row. */
const OPEN_ROW_KIND = (index) => `(() => {
  const row = document.querySelector('[data-generate-field="${index}"]');
  const trigger = row && row.querySelector('button[aria-haspopup="listbox"]');
  if (!trigger) return false;
  trigger.click();
  return true;
})()`;

/** The listbox commits on POINTERDOWN, not click — "so the pick lands before the
 * panel closes". A synthesised `click()` therefore selects nothing while
 * returning perfectly true, which is the shape of proof that passes vacuously. */
const PICK_OPTION = (pattern) => `(() => {
  const option = [...document.querySelectorAll('[role="option"]')]
    .find((o) => new RegExp(${JSON.stringify(pattern)}, "i").test(o.textContent || ""));
  if (!option) return false;
  option.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, cancelable: true }));
  return true;
})()`;

/** Open a labelled kit Select (the test panel's item picker). */
const OPEN_LABELLED_SELECT = (labelPattern) => `(() => {
  const label = [...document.querySelectorAll("label")]
    .find((l) => new RegExp(${JSON.stringify(labelPattern)}, "i").test(l.textContent || ""));
  const trigger = label && document.getElementById(label.htmlFor);
  if (!trigger) return false;
  trigger.click();
  return true;
})()`;

const ROW_ERROR = (index) => `(() => {
  const row = document.querySelector('[data-generate-field="${index}"]');
  const message = row && row.querySelector("p");
  return message ? message.textContent.trim() : "";
})()`;

/** Add choices to an enum row's token editor, one Enter at a time. */
const ADD_CHOICES = (index, values) => `(() => {
  const row = document.querySelector('[data-generate-field="${index}"]');
  const input = row && [...row.querySelectorAll("input")][1];
  if (!input) return false;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  for (const value of ${JSON.stringify(values)}) {
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  }
  return true;
})()`;

const OPEN_TOKENS = `(() => {
  const button = document.querySelector("[data-token-reference] button[aria-expanded]");
  if (!button) return false;
  if (button.getAttribute("aria-expanded") !== "true") button.click();
  return true;
})()`;

const TOKENS_OFFERED = `(() => {
  const buttons = [...document.querySelectorAll("[data-token-reference] [data-token]")];
  return {
    all: buttons.map((b) => b.getAttribute("data-token")),
    variables: [...document.querySelectorAll("[data-token-variables] [data-token]")].map((b) =>
      b.getAttribute("data-token"),
    ),
  };
})()`;

const CLICK_TOKEN = (token) => `(() => {
  const button = document.querySelector('[data-token-reference] [data-token="${token}"]');
  if (!button) return false;
  button.click();
  return true;
})()`;

/** Put a value param into TOKEN mode and focus its input, so the picker has a
 * target. Returns what the field holds afterwards. */
const TOKEN_MODE = (label) => `(() => {
  const wrap = document.querySelector('[data-tokenizable="${label}"]');
  if (!wrap) return { present: false };
  const toggle = wrap.querySelector("button[aria-pressed]");
  if (toggle.getAttribute("aria-pressed") !== "true") toggle.click();
  return { present: true, pressed: toggle.getAttribute("aria-pressed") };
})()`;

const FOCUS_TOKEN_FIELD = (label) => `(() => {
  const input = document.querySelector('[data-tokenizable="${label}"] input');
  if (!input) return false;
  input.focus();
  return true;
})()`;

const TOKEN_FIELD_VALUE = (label) => `(() => {
  const input = document.querySelector('[data-tokenizable="${label}"] input');
  return input ? input.value : null;
})()`;

const CANVAS_NAMES = `(() => Object.fromEntries(
  [...document.querySelectorAll("[data-node-id]")].map((card) => [
    card.getAttribute("data-node-id"),
    card.querySelector("[data-node-name]")?.getAttribute("data-node-name") ?? "",
  ]),
))()`;

const SAVE = `(() => {
  const button = [...document.querySelectorAll("button[type=submit]")]
    .find((b) => /save changes|create automation/i.test(b.textContent || ""));
  if (!button) return false;
  button.click();
  return true;
})()`;

const SAVE_STATE = `(() => {
  const text = document.body.innerText;
  const match = text.match(/Rejected on save:[^\\n]*/);
  return { rejected: match ? match[0] : null, saved: /\\bSaved\\b/.test(text) };
})()`;

const RUN_TEST = `(() => {
  const button = [...document.querySelectorAll("button")].find((b) => /^Run$/.test((b.textContent || "").trim()));
  if (!button) return false;
  button.click();
  return true;
})()`;

const TEST_RESULT = `(() => {
  const produced = [...document.querySelectorAll("[data-node-produced] li")].map((li) => ({
    token: li.querySelector("code")?.textContent ?? "",
    value: li.querySelector("span")?.textContent ?? "",
  }));
  const actions = [...document.querySelectorAll("[data-action-preview]")].map((li) => ({
    node: li.getAttribute("data-action-preview"),
    resolves: li.getAttribute("data-action-resolves") === "true",
    detail: li.querySelector("[data-action-detail]")?.textContent?.trim() ?? "",
    resolved: [...li.querySelectorAll("[data-action-resolved] li")].map((row) =>
      [...row.querySelectorAll("code, span")].map((el) => el.textContent.trim()),
    ),
  }));
  return { produced, actions };
})()`;

async function openEditor() {
  await session.navigate(`${baseUrl}/settings/automations`, 2200);
  const opened = await session.eval(OPEN_RULE);
  await sleep(2500);
  return opened;
}

/** Select a node on the canvas by the type printed on its card.
 *
 * A REAL click through the input pipeline, not a synthesised MouseEvent: React
 * Flow's pointer handler reads `event.view.document`, and a hand-built event
 * carries `view: null`. The matcher is built with `new Function` because
 * `clickAt` STRINGIFIES it into the page, where a closed-over variable does not
 * exist — an arrow function capturing `type` throws a ReferenceError that reads
 * like a product bug. */
const selectNode = (type) =>
  session.click(
    "[data-node-id]",
    new Function("text", `return text.includes(${JSON.stringify(type)})`),
  );

// --- 1. drop the generate node and configure it -------------------------------

const opened = await openEditor();
await session.eval(SEARCH_NODES("generate"));
await sleep(600);
const addedGenerate = await session.eval(ADD_NODE("generate with ai"));
await sleep(1400);

const autoName = await session.eval(NAME_FIELD);
const canvasAfterAdd = await session.eval(CANVAS_NAMES);
const freshForm = await session.eval(GENERATE_FORM);

// A name that could never appear in a token is refused as it is typed.
await session.eval(SET_FIELD("name \\(for tokens\\)", "Triage Result"));
await sleep(300);
const badName = await session.eval(NAME_FIELD);
await session.eval(SET_FIELD("name \\(for tokens\\)", NODE_NAME));
await sleep(300);
const goodName = await session.eval(NAME_FIELD);

await session.eval(SET_FIELD("what to work out", "Triage this outage report."));
await sleep(200);

// Two enum values: one the project can take, one it cannot.
async function addEnumRow(index, name, choices) {
  await session.eval(ADD_VALUE_ROW);
  await sleep(350);
  await session.eval(NAME_VALUE_ROW(index, name));
  await sleep(250);
  await session.eval(OPEN_ROW_KIND(index));
  await sleep(350);
  await session.eval(PICK_OPTION("one of"));
  await sleep(350);
  await session.eval(ADD_CHOICES(index, choices));
  await sleep(400);
}

await addEnumRow(0, "priority", ["low", "normal", "high", "blocker"]);
await addEnumRow(1, "state", [...stateNames, ANSWER.state]);

// …and one that cannot be a token at all, to see the inline refusal.
await session.eval(ADD_VALUE_ROW);
await sleep(350);
await session.eval(NAME_VALUE_ROW(2, "Team Name"));
await sleep(300);
const rowError = await session.eval(ROW_ERROR(2));
await session.click(`[data-generate-field="2"] button[aria-label]`, () => true);
await sleep(300);
const formAfter = await session.eval(GENERATE_FORM);

const saveOne = await session.eval(SAVE);
await sleep(1600);
const savedGenerate = await session.eval(SAVE_STATE);

// --- 2. wire the actions ------------------------------------------------------
//
// The NODES are added and configured in the editor; the EDGES are written
// through the API. React Flow's connection is a pointer drag between two 9px
// handles across a zoomed, panned canvas — synthesising it would be a proof of
// the harness's arithmetic rather than of this feature, and no proof in this
// repo does it.

const stored = (parsed(await session.eval(api("GET", "/automations"))) ?? []).find(
  (entry) => entry.id === rule?.id,
);
const generateNode = (stored?.nodes ?? []).find((node) => node.type === "ai.generate");

await session.eval(
  api("PATCH", `/automations/${rule?.id}`, {
    nodes: [
      ...(stored?.nodes ?? []),
      {
        id: "prio",
        kind: "action",
        type: "action.set_priority",
        params: { priority: "normal" },
      },
      // A REAL state name: `SetStateParams.state` has min_length=1, so an empty
      // one is a 422 and the whole PATCH would silently do nothing. The UI
      // replaces it with the token below.
      { id: "st", kind: "action", type: "action.set_state", params: { state: stateNames[0] ?? "Todo" } },
    ],
    edges: [
      { source: "trg", port: "out", target: generateNode?.id },
      { source: generateNode?.id, port: "out", target: "prio" },
      { source: "prio", port: "out", target: "st" },
    ],
  }),
);

// --- 3. the token picker, from a node BELOW the producer ----------------------

await openEditor();
await selectNode("action.set_priority");
await sleep(900);
await session.eval(TOKEN_MODE("Priority"));
await sleep(300);
await session.eval(FOCUS_TOKEN_FIELD("Priority"));
await session.eval(OPEN_TOKENS);
await sleep(400);
const offered = await session.eval(TOKENS_OFFERED);
const inserted = await session.eval(CLICK_TOKEN(`{{${NODE_NAME}.priority}}`));
await sleep(400);
const priorityValue = await session.eval(TOKEN_FIELD_VALUE("Priority"));

// The producer itself can read NOTHING from downstream — the picker walks the
// edges backwards, so a node above the producer sees no variables at all.
await selectNode("ai.generate");
await sleep(700);
await session.eval(OPEN_TOKENS);
await sleep(300);
const offeredAtProducer = await session.eval(TOKENS_OFFERED);

// The state action reads the field the model will answer with a value this
// project does not have.
await selectNode("action.set_state");
await sleep(800);
await session.eval(SET_FIELD("state name", `{{${NODE_NAME}.state}}`));
await sleep(300);
await session.eval(SAVE);
await sleep(1700);
const savedChain = await session.eval(SAVE_STATE);

const shotLight = await session.send("Page.captureScreenshot", { format: "png" });
writeFileSync("/tmp/radd-1073-builder.png", Buffer.from(shotLight.data, "base64"));

// --- 4. run it ----------------------------------------------------------------

await session.eval(OPEN_LABELLED_SELECT("as if it fired for"));
await sleep(500);
const pickedItem = await session.eval(PICK_OPTION("checkout is down"));
await sleep(500);
const ran = await session.eval(RUN_TEST);
await sleep(3500);
const result = await session.eval(TEST_RESULT);

const shotRun = await session.send("Page.captureScreenshot", { format: "png" });
writeFileSync("/tmp/radd-1073-dryrun.png", Buffer.from(shotRun.data, "base64"));

// --- 5. both themes -----------------------------------------------------------

const themes = {};
for (const theme of ["dark", "light"]) {
  await session.eval(
    `document.documentElement.classList.toggle("light", ${JSON.stringify(theme)} === "light"); "ok"`,
  );
  await sleep(400);
  themes[theme] = await session.eval(`(() => {
    const token = document.querySelector("[data-node-produced] code");
    const skipped = [...document.querySelectorAll("[data-action-preview]")]
      .find((li) => li.getAttribute("data-action-resolves") === "false");
    const detail = skipped && skipped.querySelector("[data-action-detail]");
    const seen = (el) => {
      if (!el) return null;
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return {
        text: el.textContent.trim().slice(0, 90),
        wide: rect.width > 20,
        onScreen: rect.height > 0,
        color: style.color,
      };
    };
    return { token: seen(token), detail: seen(detail) };
  })()`);
  const shot = await session.send("Page.captureScreenshot", { format: "png" });
  writeFileSync(`/tmp/radd-1073-dryrun-${theme}.png`, Buffer.from(shot.data, "base64"));
}

// --- teardown -----------------------------------------------------------------

if (rule) await session.eval(api("DELETE", `/automations/${rule.id}`));
if (provider) await session.eval(api("DELETE", `/ai/providers/${provider.id}`));

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const producedFor = (name) =>
  result.produced.find((entry) => entry.token === `{{${NODE_NAME}.${name}}}`);
const action = (nodeId) => result.actions.find((entry) => entry.node === nodeId);

const failed = report(
  {
    "logged in": loginStatus === 204,
    "hover is capable (the flag reached this browser)": hoverCapable === true,
    "fixtures created": Boolean(rule?.id && project?.id && item?.id && provider?.id),
    "the chat role points at the fake model": roleSet.status === 200,
    "the editor opened": opened === true && addedGenerate === true,

    "a fresh producer arrives NAMED": /^generate_\d+$/.test(autoName.value ?? ""),
    "and the canvas shows the name": Object.values(canvasAfterAdd).some((name) =>
      /^generate_\d+$/.test(name),
    ),
    "the bespoke form renders rows, not a text box for the array":
      freshForm.addButton === true && freshForm.hasFieldsTextInput === false,

    "a name that could never be a token is refused inline":
      badName.invalid === true && /lowercase/i.test(badName.message ?? ""),
    "…and a usable one is accepted": goodName.invalid === false && goodName.value === NODE_NAME,
    "a field name that could never be a token is refused too": /lowercase/i.test(rowError ?? ""),
    "the two usable value rows remain": formAfter.rows === 2,
    "the node saves": savedGenerate.saved === true && savedGenerate.rejected === null,

    "the picker offers the producer's outputs downstream": ["text", "priority", "state"].every(
      (name) => (offered.variables ?? []).includes(`{{${NODE_NAME}.${name}}}`),
    ),
    "…and still offers the event roots": (offered.all ?? []).includes("{{item.key}}"),
    "the producer itself is offered no variables (the walk is backwards)": same(
      offeredAtProducer.variables,
      [],
    ),
    "clicking a token inserts it into the focused field":
      inserted === true && priorityValue === `{{${NODE_NAME}.priority}}`,
    "the chain saves": savedChain.saved === true && savedChain.rejected === null,

    "the dry run ran against the fixture item": pickedItem === true && ran === true,
    "the model was called exactly once": modelCalls === 1,
    "…with the enum encoded in the request schema": Boolean(
      lastRequest &&
        JSON.stringify(lastRequest).includes('"blocker"') &&
        JSON.stringify(lastRequest).includes(ANSWER.state),
    ),
    "the dry run reports what the node produced": Boolean(
      producedFor("priority") && producedFor("text"),
    ),
    "…with the value the model gave": (producedFor("priority")?.value ?? "").includes("high"),

    "the resolvable action would apply": action("prio")?.resolves === true,
    "…showing what its token became": (action("prio")?.resolved ?? []).some((row) =>
      row.join(" ").includes(`{{${NODE_NAME}.priority}}`) && row.join(" ").includes("high"),
    ),
    "the unresolvable one is SKIPPED, not applied": action("st")?.resolves === false,
    "…naming the value and the vocabulary": Boolean(
      action("st")?.detail?.includes(ANSWER.state) && action("st")?.detail?.includes("states:"),
    ),

    "the produced token reads in dark": themes.dark.token?.wide === true,
    "the produced token reads in light": themes.light.token?.wide === true,
    "the skip reason reads in dark": themes.dark.detail?.onScreen === true,
    "the skip reason reads in light": themes.light.detail?.onScreen === true,
    "the theme really changed the ink": themes.dark.token?.color !== themes.light.token?.color,

    // Plugin UI remotes are built into the image by `build-all.mjs`; a bare
    // `vite build` leaves them absent and the loader quarantines each one.
    "no console errors": session.consoleErrors.filter(
      (line) => !/plugin UI .* failed to load \(quarantined\)/.test(line),
    ).length === 0,
  },
  {
    autoName,
    forms: { fresh: freshForm, after: formAfter, rowError },
    names: { bad: badName, good: goodName },
    tokens: { offered, atProducer: offeredAtProducer, priorityValue },
    model: { calls: modelCalls, schema: lastRequest?.response_format ?? lastRequest?.tools ?? null },
    run: result,
    saves: { generate: savedGenerate, chain: savedChain },
    themes,
    screenshots: [
      "/tmp/radd-1073-builder.png",
      "/tmp/radd-1073-dryrun.png",
      "/tmp/radd-1073-dryrun-dark.png",
      "/tmp/radd-1073-dryrun-light.png",
    ],
    consoleErrors: session.consoleErrors
      .filter((line) => !/plugin UI .* failed to load \(quarantined\)/.test(line))
      .slice(0, 5),
  },
);

done(failed);

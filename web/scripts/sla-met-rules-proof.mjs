#!/usr/bin/env node
/**
 * Proof for RADD-1299: an SLA target says what "met" means.
 *
 *   node web/scripts/sla-met-rules-proof.mjs http://127.0.0.1:8000 admin@example.com change-me
 *
 * The DEV Triage story, through the real UI:
 *   1. on Project settings → SLAs, the form offers "Response is met when";
 *      choosing "leaves these states" reveals a state picker and blocks Create
 *      until a state is picked;
 *   2. the policy is created FROM THE FORM with the project's first state, and
 *      the list summary says "met on leaving <state>";
 *   3. an issue in that state has a RUNNING response timer — a reply from
 *      someone else does not meet it (the rule is the state, not a reply);
 *   4. moving the issue to another state MEETS it;
 *   5. the reporter-team filter is on the form ("Any reporter" until set).
 * The fixture project is deleted at the end.
 */
import { resolve } from "node:path";
import { clickAt, openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
if (!baseUrl || !adminEmail || !adminPassword) {
  console.error("usage: sla-met-rules-proof.mjs <baseUrl> <adminEmail> <adminPassword>");
  process.exit(2);
}
const PORT = 9501;
const TMP = process.env.TMPDIR || "/tmp";
const PROFILE = resolve(TMP, "radd-sla-met-rules-proof");
const SHOTS = resolve(TMP, "radd-sla-met-rules-proof-shots");
const STAMP = Date.now().toString(36).slice(-5);
const KEY = `SM${STAMP.slice(-4).toUpperCase()}`;
const COLLEAGUE = `sla-colleague-${STAMP}@example.test`;

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

/** Set a React-controlled input's value the way typing would. */
const typeInto = (selector, value) => `(() => {
  const input = document.querySelector(${JSON.stringify(selector)});
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  setter.call(input, ${JSON.stringify(value)});
  input.dispatchEvent(new Event("input", { bubbles: true }));
  return !!input;
})()`;

const matcher = (text) => new Function("t", `return t.trim() === ${JSON.stringify(text)}`);
const startsWith = (text) => new Function("t", `return t.trim().startsWith(${JSON.stringify(text)})`);

async function main() {
  const { session, close } = await openBrowser({ port: PORT, profile: PROFILE, width: 1400, height: 1200, scale: 1 });
  const send = session.send;
  const checks = {};
  const context = { key: KEY };
  let fixture = null;
  try {
    await session.navigate(baseUrl + "/login", 800);
    await session.login(baseUrl, adminEmail, adminPassword);
    fixture = await session.eval(`(async () => { ${API}
      const project = await api("POST", "/projects", { key: ${JSON.stringify(KEY)}, name: "SLA met rules" });
      const states = (await api("GET", "/states?project_id=" + project.body.id)).body;
      const colleague = await api("POST", "/users", { email: ${JSON.stringify(COLLEAGUE)}, name: "Colleague", password: "sla-colleague-1", instance_role: "admin" });
      return { project: project.body, states, colleague: colleague.body };
    })()`);
    const ordered = [...fixture.states].sort((a, b) => a.position - b.position);
    const first = ordered[0];
    const other = ordered[1];
    context.states = { first: first.name, other: other.name };

    // 1 — the form.
    await session.navigate(`${baseUrl}/p/${KEY}/settings/sla`, 3000);
    await session.eval(typeInto('input[placeholder="TD standard"]', "Triage promise"));
    const offered = await session.eval(`!!document.querySelector('[data-met-rule="response"]')`);
    await clickAt(send, '[data-met-rule="response"] button[aria-haspopup="listbox"]');
    await sleep(300);
    await clickAt(send, '[role="option"]', startsWith("Issue leaves these states"));
    await sleep(300);
    const blocked = await session.eval(`(() => {
      const submit = [...document.querySelectorAll("form button[type=submit]")].find((b) => b.textContent.includes("Create policy"));
      return { picker: !!document.querySelector('[data-met-rule="response"] input'), disabled: submit?.disabled ?? null };
    })()`);
    checks["1. the form offers 'met when', and 'leaves states' needs a state before Create"] =
      offered && blocked.picker && blocked.disabled === true;
    const reporterFilter = await session.eval(`document.querySelector("[data-reporter-teams]")?.textContent ?? ""`);
    checks["5. the reporter-team filter is on the form"] = reporterFilter.includes("Any reporter");

    // 2 — pick the first state, create.
    await session.eval(`document.querySelector('[data-met-rule="response"] input').focus()`);
    await session.eval(typeInto('[data-met-rule="response"] input', first.name));
    await sleep(300);
    await clickAt(send, '[data-met-rule="response"] [role="option"]', matcher(first.name));
    await sleep(300);
    await session.screenshot(resolve(SHOTS, "form.png"));
    await clickAt(send, "form button[type=submit]", startsWith("Create policy"));
    await sleep(1500);
    const created = await session.eval(`(async () => { ${API}
      return (await api("GET", "/sla-policies?project_id=${fixture.project.id}")).body;
    })()`);
    const policy = (Array.isArray(created) ? created : []).find((p) => p.name === "Triage promise");
    context.policy = policy && { met_on: policy.response_met_on, states: policy.response_state_ids };
    const listed = await session.eval(`document.body.innerText.includes("met on leaving ${first.name}")`);
    checks["2. the policy is saved from the form and summarised as 'met on leaving <state>'"] =
      policy?.response_met_on === "leaves_states" && policy.response_state_ids[0] === first.id && listed;
    await session.screenshot(resolve(SHOTS, "list.png"));

    // 3 — an issue in that state: running; a colleague's reply does not meet it.
    const item = await session.eval(`(async () => { ${API}
      return (await api("POST", "/items", { project_id: "${fixture.project.id}", title: "Needs triage", state_id: "${first.id}" })).body;
    })()`);
    await session.eval(`fetch("/api/v1/auth/logout", { method: "POST" })`);
    await session.login(baseUrl, COLLEAGUE, "sla-colleague-1");
    await session.eval(`(async () => { ${API}
      await api("POST", "/items/${item.id}/comments", { body: "Replying is not triaging" });
    })()`);
    await session.eval(`fetch("/api/v1/auth/logout", { method: "POST" })`);
    await session.login(baseUrl, adminEmail, adminPassword);
    const timer = async () => session.eval(`(async () => { ${API}
      const sla = (await api("GET", "/items/${item.id}/sla")).body;
      return sla.entries?.[0]?.timers?.find((t) => t.kind === "response") ?? null;
    })()`);
    const running = await timer();
    context.running = running && { met_at: running.met_at, remaining: running.remaining_seconds };
    checks["3. in the start state the timer runs, and a reply does not meet it"] =
      !!running && running.met_at === null && running.remaining_seconds > 0;

    // 4 — move it out: met.
    await session.eval(`(async () => { ${API}
      await api("PATCH", "/items/${item.id}", { state_id: "${other.id}" });
    })()`);
    const met = await timer();
    context.met = met && { met_at: met.met_at, breached: met.breached };
    checks["4. moving it out of the state meets the target"] = !!met?.met_at && met.breached === false;
  } finally {
    if (fixture) {
      context.cleanup = await session.eval(`(async () => { ${API}
        return {
          project: (await api("DELETE", "/projects/${fixture.project.id}")).status,
          colleague: (await api("DELETE", "/users/${fixture.colleague.id}")).status,
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

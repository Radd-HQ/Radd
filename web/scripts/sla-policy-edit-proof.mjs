#!/usr/bin/env node
/**
 * Proof for RADD-1300: SLA policies can be edited, not only created.
 *
 *   node web/scripts/sla-policy-edit-proof.mjs http://127.0.0.1:8000 admin@example.com change-me
 *
 *   1. Edit on a policy row opens the form SEEDED with that policy (name,
 *      targets, warning, business window);
 *   2. saving writes a PATCH: same id, same position; the new name, target and
 *      "met when" rule are stored, and the list summary shows them;
 *   3. fields CLEARED in the form are cleared on the server (the warning and
 *      the business window), not left as they were;
 *   4. Cancel discards: a changed name is not saved.
 * The fixture project is deleted at the end.
 */
import { resolve } from "node:path";
import { clickAt, openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
if (!baseUrl || !adminEmail || !adminPassword) {
  console.error("usage: sla-policy-edit-proof.mjs <baseUrl> <adminEmail> <adminPassword>");
  process.exit(2);
}
const PORT = 9502;
const TMP = process.env.TMPDIR || "/tmp";
const PROFILE = resolve(TMP, "radd-sla-policy-edit-proof");
const SHOTS = resolve(TMP, "radd-sla-policy-edit-proof-shots");
const STAMP = Date.now().toString(36).slice(-5);
const KEY = `SE${STAMP.slice(-4).toUpperCase()}`;

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

const FORM = '[data-sla-policy-form="edit"]';

/** Set a React-controlled input's value the way typing would. */
const setValue = (selector, value) => `(() => {
  const input = document.querySelector(${JSON.stringify(selector)});
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  setter.call(input, ${JSON.stringify(value)});
  input.dispatchEvent(new Event("input", { bubbles: true }));
  return !!input;
})()`;

const startsWith = (text) => new Function("t", `return t.trim().startsWith(${JSON.stringify(text)})`);
const equals = (text) => new Function("t", `return t.trim() === ${JSON.stringify(text)}`);

async function main() {
  const { session, close } = await openBrowser({ port: PORT, profile: PROFILE, width: 1400, height: 1300, scale: 1 });
  const send = session.send;
  const checks = {};
  const context = { key: KEY };
  let fixture = null;
  try {
    await session.navigate(baseUrl + "/login", 800);
    await session.login(baseUrl, adminEmail, adminPassword);
    fixture = await session.eval(`(async () => { ${API}
      const project = await api("POST", "/projects", { key: ${JSON.stringify(KEY)}, name: "SLA edit proof" });
      const states = (await api("GET", "/states?project_id=" + project.body.id)).body;
      const catchAll = await api("POST", "/sla-policies", { project_id: project.body.id, name: "Catch-all", response_minutes: 480, position: 0 });
      const policy = await api("POST", "/sla-policies", {
        project_id: project.body.id, name: "Original", response_minutes: 60, warning_minutes: 30,
        business_start_minute: 540, business_end_minute: 1020, position: 1,
      });
      return { project: project.body, states, catchAll: catchAll.body, policy: policy.body };
    })()`);
    const first = [...fixture.states].sort((a, b) => a.position - b.position)[0];
    const read = () => session.eval(`(async () => { ${API}
      return (await api("GET", "/sla-policies?project_id=${fixture.project.id}")).body.find((p) => p.id === "${fixture.policy.id}");
    })()`);

    // 1 — the seeded form.
    await session.navigate(`${baseUrl}/p/${KEY}/settings/sla`, 3000);
    await clickAt(send, 'button[aria-label="Edit Original"]');
    await sleep(600);
    const seeded = await session.eval(`(() => {
      const form = document.querySelector('${FORM}');
      if (!form) return null;
      const value = (label) => [...form.querySelectorAll("label")].find((l) => l.textContent.trim() === label)
        ?.parentElement?.querySelector("input")?.value ?? null;
      return { name: value("Policy name"), response: value("Response target"), warn: value("Warn before breach"),
        start: form.querySelector('input[aria-label="Business hours start"]')?.value,
        end: form.querySelector('input[aria-label="Business hours end"]')?.value,
        createFormHidden: !document.querySelector('[data-sla-policy-form="create"]') };
    })()`);
    context.seeded = seeded;
    checks["1. Edit opens the form seeded with the policy"] =
      seeded?.name === "Original" && seeded.response === "1h" && seeded.warn === "30m" &&
      seeded.start === "09:00" && seeded.end === "17:00" && seeded.createFormHidden;
    await session.screenshot(resolve(SHOTS, "seeded.png"));

    // 2/3 — change name + target + rule, clear the warning and the window, save.
    await session.eval(`(() => {
      const form = document.querySelector('${FORM}');
      const byLabel = (label) => [...form.querySelectorAll("label")].find((l) => l.textContent.trim() === label)?.parentElement?.querySelector("input");
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      for (const [el, value] of [[byLabel("Policy name"), "Edited"], [byLabel("Response target"), "4h"], [byLabel("Warn before breach"), ""],
          [form.querySelector('input[aria-label="Business hours start"]'), ""], [form.querySelector('input[aria-label="Business hours end"]'), ""]]) {
        setter.call(el, value);
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      }
    })()`);
    await clickAt(send, `${FORM} [data-met-rule="response"] button[aria-haspopup="listbox"]`);
    await sleep(300);
    await clickAt(send, '[role="option"]', startsWith("Issue leaves these states"));
    await sleep(300);
    await session.eval(setValue(`${FORM} [data-met-rule="response"] input`, first.name));
    await sleep(300);
    await clickAt(send, `${FORM} [data-met-rule="response"] [role="option"]`, equals(first.name));
    await sleep(300);
    await clickAt(send, `${FORM} button[type=submit]`, startsWith("Save changes"));
    await sleep(1500);
    const saved = await read();
    context.saved = saved && {
      id: saved.id, position: saved.position, name: saved.name, response: saved.response_minutes,
      warning: saved.warning_minutes, window: [saved.business_start_minute, saved.business_end_minute],
      met_on: saved.response_met_on, states: saved.response_state_ids,
    };
    const summary = await session.eval(`document.querySelector('[data-sla-policy="Edited"]')?.textContent ?? ""`);
    context.summary = summary;
    checks["2. Save is a PATCH (same id and position) storing the new values"] =
      saved?.id === fixture.policy.id && saved.position === 1 && saved.name === "Edited" &&
      saved.response_minutes === 240 && saved.response_met_on === "leaves_states" && saved.response_state_ids[0] === first.id &&
      summary.includes(`met on leaving ${first.name}`) && summary.includes("response 4h");
    checks["3. cleared fields are cleared on the server"] =
      saved?.warning_minutes === null && saved.business_start_minute === null && saved.business_end_minute === null;
    await session.screenshot(resolve(SHOTS, "saved.png"));

    // 4 — Cancel discards.
    await clickAt(send, 'button[aria-label="Edit Edited"]');
    await sleep(500);
    await session.eval(`(() => {
      const form = document.querySelector('${FORM}');
      const el = [...form.querySelectorAll("label")].find((l) => l.textContent.trim() === "Policy name").parentElement.querySelector("input");
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      setter.call(el, "Should not stick");
      el.dispatchEvent(new Event("input", { bubbles: true }));
    })()`);
    await clickAt(send, `${FORM} button`, equals("Cancel"));
    await sleep(800);
    const after = await read();
    const closed = await session.eval(`!document.querySelector('${FORM}')`);
    checks["4. Cancel discards the change and closes the editor"] = after?.name === "Edited" && closed;
  } finally {
    if (fixture) {
      context.cleanup = await session.eval(`(async () => { ${API}
        return (await api("DELETE", "/projects/${fixture.project.id}")).status;
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

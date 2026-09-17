/**
 * Render proof for the mail routing trace (RADD-994).
 *
 * The panel's whole job is answering "why didn't my rule fire", and every bug
 * this proof pins was a way of answering it with silence — none of which `tsc`
 * can see, because a rule that is absent from a list renders perfectly.
 *
 *  - **All five statuses reach the DOM, in chain order.** A rule switched off, a
 *    rule below the winner and a rule that was deleted used to be the same
 *    nothing. The proof builds one chain that produces declined / errored /
 *    matched / disabled / not_reached in that order and reads them back off
 *    `data-rule-status`, which is the wire contract; the labels beside them are
 *    prose and will be reworded.
 *  - **The detail is readable, not clipped.** It shipped inside a `flex-[2]
 *    truncate` span with no title attribute — the most informative field on the
 *    panel ("the classifier failed (TimeoutError)"), cut off in a modal with no
 *    way to widen it. The check measures: the detail line must wrap BELOW the
 *    rule name and fit its own box. Against the old markup the errored rule's
 *    52-character detail overflows a ~160px column, so this fails.
 *  - **A rule that matched while naming no project says so.** Two wrong
 *    sentences were available and the code used both — `decide` said "rule: X",
 *    naming a destination the rule never chose, and the dry run recomputed the
 *    line from `project_id` into "no rule matched", denying the match entirely.
 *    Either one sends an admin to debug the rule that behaved.
 *  - **The rule editor states the answer the admin did not write.** The model is
 *    always offered "None of these"; a category list that hides it gets fought
 *    in the prompt or duplicated as an "Other" row.
 *
 * The DECLINE wording ("…declined — the model answered 'None of these'") is
 * pinned by `test_mail_routing.py` instead: reaching it needs a real chat role
 * and a model round trip, which a render proof has no business arranging.
 *
 * Seeds its own source + chain over the API and deletes them again — the rules
 * cascade with the source, so the instance is left as it was found.
 *
 * Usage: node scripts/mail-routing-trace-proof.mjs <baseUrl> <email> <password>
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, email, password] = process.argv.slice(2);
const PORT = 9459;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-mail-trace-proof");

/** The address the sample message is delivered to — unique per run, so a
 *  leftover source from an interrupted run cannot answer for this one. */
const STAMP = Date.now().toString(36);
const INBOX = `trace-${STAMP}@radd-hq.com`;
const SENDER = "probe@customer.example";

/** The detail an llm rule with no categories records. Copied from
 *  `routing._match_llm` deliberately: if that sentence is reworded the proof
 *  should fail and be updated, not quietly stop measuring anything. */
const ERRORED_DETAIL = "no categories configured — this rule can never match";

/** Run `fetch` inside the page so the session cookie applies. */
function apiCall(session, method, path, body) {
  const payload = body === undefined ? "undefined" : JSON.stringify(JSON.stringify(body));
  return session.eval(`(async () => {
    const body = ${payload};
    const r = await fetch(${JSON.stringify("/api/v1" + path)}, {
      method: ${JSON.stringify(method)},
      credentials: "include",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body || undefined,
    });
    const text = await r.text();
    return { status: r.status, body: text ? JSON.parse(text) : null };
  })()`);
}

async function seed(session) {
  const projects = await apiCall(session, "GET", "/projects");
  if (projects.status !== 200 || !projects.body.length) {
    throw new Error(`no projects to route into (GET /projects → ${projects.status})`);
  }
  const [home, elsewhere] = [projects.body[0], projects.body[1] ?? projects.body[0]];

  const source = await apiCall(session, "POST", "/mail/sources", {
    name: `Trace proof ${STAMP}`,
    kind: "webhook",
    address: INBOX,
    default_project_id: home.id,
  });
  if (source.status !== 201) {
    throw new Error(`could not create the source: ${source.status} ${JSON.stringify(source.body)}`);
  }

  // One chain, five outcomes, in this order. Each rule is the shortest thing
  // that produces its status, so a failure names one cause.
  const chain = [
    // 1. runs, does not claim the message.
    { name: "1 urgent subjects", rule_type: "subject", config: { contains: ["[URGENT]"] },
      project_id: elsewhere.id, position: 1 },
    // 2. broken configuration, not a classification failure — and the one rule
    //    here with a detail long enough to overflow the old truncating column.
    { name: "2 classifier with no categories", rule_type: "llm",
      config: { prompt: "classify", answers: [] }, position: 2 },
    // 3. the winner.
    { name: "3 the proof inbox", rule_type: "recipient", config: { addresses: [INBOX] },
      project_id: elsewhere.id, position: 3 },
    // 4. below the winner AND switched off: reads OFF, because reordering a
    //    disabled rule changes nothing.
    { name: "4 switched off", rule_type: "sender", config: { patterns: ["@customer.example"] },
      project_id: home.id, position: 4, enabled: false },
    // 5. below the winner and enabled: it WOULD have matched this sender.
    { name: "5 never consulted", rule_type: "sender", config: { patterns: ["@customer.example"] },
      project_id: home.id, position: 5 },
  ];
  for (const rule of chain) {
    const made = await apiCall(session, "POST", `/mail/sources/${source.body.id}/rules`, {
      enabled: true,
      ...rule,
    });
    if (made.status !== 201) {
      throw new Error(`rule ${rule.name}: ${made.status} ${JSON.stringify(made.body)}`);
    }
  }

  // A second source whose only rule matches while naming NO project. It stops
  // the chain and still lands on the source default, which is the case both old
  // sentences described wrongly.
  const orphan = await apiCall(session, "POST", "/mail/sources", {
    name: `Trace proof projectless ${STAMP}`,
    kind: "webhook",
    address: `orphan-${STAMP}@radd-hq.com`,
    default_project_id: home.id,
  });
  if (orphan.status !== 201) {
    throw new Error(`could not create the second source: ${orphan.status}`);
  }
  await apiCall(session, "POST", `/mail/sources/${orphan.body.id}/rules`, {
    name: "Catch-all",
    rule_type: "recipient",
    enabled: true,
    config: { addresses: [`orphan-${STAMP}@radd-hq.com`] },
    project_id: null,
    position: 1,
  });

  return { sourceId: source.body.id, orphanId: orphan.body.id, expectedKey: elsewhere.key };
}

/** Open Settings → Email, then this source's Routing chain. */
async function openChain(session, sourceName) {
  await session.navigate(`${baseUrl}/settings/email`, 3000);
  for (let i = 0; i < 20; i++) {
    const ready = await session.eval(
      `document.body.innerText.includes(${JSON.stringify(sourceName)})`,
    );
    if (ready) break;
    await sleep(500);
  }
  // The Routing button carries its rule count, so match on the word alone.
  await session.eval(`(() => {
    const row = [...document.querySelectorAll("li")]
      .find((li) => (li.innerText || "").includes(${JSON.stringify(sourceName)}));
    const button = row && [...row.querySelectorAll("button")]
      .find((b) => /^Routing/.test(b.textContent || ""));
    if (button) button.click();
    return Boolean(button);
  })()`);
  await sleep(800);
}

/** Fill the dry run and press Check. */
async function runPreview(session, { recipient, sender, subject }) {
  await session.click("button", (t) => /where a message lands/i.test(t));
  await sleep(700);
  await session.eval(`(() => {
    const dialogs = [...document.querySelectorAll('[role="dialog"]')];
    const dialog = dialogs[dialogs.length - 1];
    const set = (label, value) => {
      const field = [...dialog.querySelectorAll("label")]
        .find((l) => new RegExp(label, "i").test(l.textContent || ""));
      const input = field && (field.control || dialog.querySelector("#" + field.htmlFor));
      if (!input) return false;
      // React listens to the DOM setter, not to .value =.
      const proto = Object.getPrototypeOf(input);
      Object.getOwnPropertyDescriptor(proto, "value").set.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    };
    return {
      recipient: set("Delivered to", ${JSON.stringify(recipient)}),
      sender: set("^From$", ${JSON.stringify(sender)}),
      subject: set("Subject", ${JSON.stringify(subject)}),
    };
  })()`);
  await sleep(300);
  await session.click("button", (t) => /^Check$/.test(t.trim()));
  for (let i = 0; i < 20; i++) {
    await sleep(400);
    const done = await session.eval(
      `Boolean(document.querySelector("[data-rule-status]")) ||` +
        ` /Opens in/.test(document.body.innerText)`,
    );
    if (done) break;
  }
}

/** Read the rendered trace back, geometry included. */
function readTrace(session) {
  return session.eval(`(() => {
    const dialogs = [...document.querySelectorAll('[role="dialog"]')];
    const dialog = dialogs[dialogs.length - 1];
    if (!dialog) return { open: false };
    const rows = [...dialog.querySelectorAll("[data-rule-status]")].map((row) => {
      const name = row.querySelector("span.truncate");
      const detail = row.querySelector("p");
      return {
        status: row.getAttribute("data-rule-status"),
        name: name ? name.textContent.trim() : "",
        detail: detail ? detail.textContent.trim() : "",
        // Clipped means the text is wider than the box that holds it. A wrapping
        // paragraph can never be; the truncating span it replaced always was.
        clipped: detail ? detail.scrollWidth > detail.clientWidth + 1 : false,
        // …and it has to be on its own LINE, not sharing the name's row.
        belowTheName:
          detail && name ? detail.getBoundingClientRect().top > name.getBoundingClientRect().top
            : false,
      };
    });
    const text = dialog.innerText;
    return {
      open: true,
      rows,
      reason: (text.match(/Opens in[\\s\\S]{0,400}/) || [""])[0],
      destination: /Opens in/.test(text),
      crashCallout: /failed and (was|were) skipped/.test(text),
    };
  })()`);
}

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE });
  const checks = {};
  let seeded = null;

  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);
  checks["headless chrome reports a real pointer"] = await session.hoverCapable();

  try {
    seeded = await seed(session);

    // --- the chain, top to bottom -------------------------------------------
    await openChain(session, `Trace proof ${STAMP}`);
    await runPreview(session, { recipient: INBOX, sender: SENDER, subject: "quarterly report" });
    const trace = await readTrace(session);
    await session.screenshot("/tmp/mail-routing-trace.png");

    checks["the dry run renders a destination"] = trace.destination === true;
    checks["every rule in the chain appears, in order"] =
      JSON.stringify((trace.rows || []).map((r) => r.status)) ===
      JSON.stringify(["declined", "errored", "matched", "disabled", "not_reached"]);
    checks["…a switched-off rule is a row, not a gap"] =
      (trace.rows || []).some((r) => r.status === "disabled" && /switched off/i.test(r.detail));
    checks["…and so is one the walk never reached"] =
      (trace.rows || []).some((r) => r.status === "not_reached" && /never consulted/.test(r.name));
    checks["the destination names the rule that won"] = /3 the proof inbox/.test(trace.reason);
    checks["a crashed rule still shouts above the destination"] = trace.crashCallout === true;

    const errored = (trace.rows || []).find((r) => r.status === "errored");
    checks["the failure detail is rendered whole"] = errored?.detail === ERRORED_DETAIL;
    checks["…on its own line, not clipped into a column"] =
      errored?.clipped === false && errored?.belowTheName === true;

    // --- a rule that matched but names no project ---------------------------
    await session.eval(`[...document.querySelectorAll("button")]
      .filter((b) => /^(Close|Cancel)$/.test((b.textContent || "").trim()))
      .forEach((b) => b.click())`);
    await sleep(600);
    await openChain(session, `Trace proof projectless ${STAMP}`);
    await runPreview(session, {
      recipient: `orphan-${STAMP}@radd-hq.com`,
      sender: SENDER,
      subject: "anything",
    });
    const orphan = await readTrace(session);
    checks["a rule that matched while naming no project says exactly that"] =
      /names no project/.test(orphan.reason) && /matched/.test(orphan.reason);
    checks["…rather than reporting that nothing matched"] =
      /no rule matched/.test(orphan.reason) === false;

    // --- the answer the admin did not write ---------------------------------
    await session.eval(`[...document.querySelectorAll("button")]
      .filter((b) => /^(Close|Cancel)$/.test((b.textContent || "").trim()))
      .forEach((b) => b.click())`);
    await sleep(600);
    await openChain(session, `Trace proof ${STAMP}`);
    await session.click("button", (t) => /add rule/i.test(t));
    await sleep(700);
    await session.click("button", (t) => /Delivered to \(alias\)/i.test(t));
    await sleep(300);
    await session.click('[role="option"]', (t) => /^AI —/.test(t));
    await sleep(500);
    const editor = await session.eval(`(() => {
      const dialogs = [...document.querySelectorAll('[role="dialog"]')];
      const dialog = dialogs[dialogs.length - 1];
      if (!dialog) return { open: false };
      const text = dialog.innerText;
      const heading = [...dialog.querySelectorAll("span")]
        .find((s) => /Categories/.test(s.textContent || ""));
      const automatic = [...dialog.querySelectorAll("div")]
        .find((d) => /None of these/.test(d.textContent || "") && d.children.length === 2);
      return {
        open: /Categories/.test(text),
        // Named where the categories are CONFIGURED, not only in the prose above.
        inTheList: Boolean(heading && automatic &&
          automatic.getBoundingClientRect().top > heading.getBoundingClientRect().top),
        saysWhereItGoes: Boolean(automatic && /default project/i.test(automatic.textContent)),
        // It is not a row the admin can edit or remove.
        notEditable: Boolean(automatic && !automatic.querySelector("input, button")),
      };
    })()`);
    checks["the AI rule editor opens its category list"] = editor.open === true;
    checks["…and states the automatic 'None of these' answer beside them"] =
      editor.inTheList === true && editor.saysWhereItGoes === true;
    checks["…as something offered, not a row to edit"] = editor.notEditable === true;

    await session.screenshot("/tmp/mail-routing-rule-editor.png");
    checks["no console errors"] = session.consoleErrors.length === 0;

    const failed = report(checks, {
      trace,
      orphan: { reason: orphan.reason },
      editor,
      consoleErrors: session.consoleErrors.slice(0, 5),
    });
    console.log("shots: /tmp/mail-routing-trace.png, /tmp/mail-routing-rule-editor.png");
    process.exit(failed ? 1 : 0);
  } finally {
    // Leave the instance as it was found; the rules cascade with the source.
    if (seeded) {
      await apiCall(session, "DELETE", `/mail/sources/${seeded.sourceId}`);
      await apiCall(session, "DELETE", `/mail/sources/${seeded.orphanId}`);
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

/**
 * Browser proof for RADD-1370: Settings → Alertmanager is the alertmanager
 * plugin's own page, and a receiver's three settings do what they say against
 * the REAL backend.
 *
 *   1. a throwaway project + receiver (API); the page lists the receiver;
 *   2. the label (blur), the comment switch and the resolve state (select) save;
 *   3. real deliveries: firing → issue labelled; repeat → internal comment;
 *      resolved → comment + the issue moved to the chosen state;
 *   4. the receiver and project are deleted again.
 *
 * Usage: node scripts/alertmanager-settings-proof.mjs <baseUrl> [email] [password]
 */
import { resolve } from "node:path";
import { outputPath, PAGE_API, sleep, waitFor } from "./lib/cdp.mjs";
import { startProof } from "./lib/proof.mjs";

const tag = `am${Date.now().toString(36)}`;
const key = `AP${Date.now().toString(36).slice(-4).toUpperCase()}`;

const { session, close, check, finish, baseUrl } = await startProof({
  port: 9483, profile: resolve(process.env.TMPDIR || "/tmp", "radd-alertmanager-proof-profile"),
});
let world = null;
try {
  // 1. the world.
  world = await session.eval(`(async () => { ${PAGE_API}
    const project = await api("POST", "/projects", { key: ${JSON.stringify(key)}, name: "Alertmanager proof" });
    const states = await api("GET", "/states?project_id=" + project.body.id);
    const token = crypto.randomUUID().replaceAll("-", "");
    const receiver = await api("POST", "/alertmanager/receivers", { name: ${JSON.stringify(tag)}, token, project_id: project.body.id });
    return { projectId: project.body.id, states: states.body.map((s) => ({ id: s.id, name: s.name })), token,
      receiverId: receiver.body?.id, status: [project.status, receiver.status] };
  })()`);
  check("a throwaway project and receiver exist", world.receiverId && world.status.join() === "201,201", JSON.stringify(world.status));
  const target = world.states.find((state) => state.name === "Done") ?? world.states.at(-1);

  await session.navigate(`${baseUrl}/settings/alertmanager`, 1500);
  const row = `[data-receiver="${tag}"]`;
  check("the plugin's page lists the receiver", await waitFor(session, `Boolean(document.querySelector('${row}'))`));
  check("the nav carries Alertmanager once",
    (await session.eval(`[...document.querySelectorAll('aside a, nav a')].filter((a) => a.textContent.trim() === "Alertmanager").length`)) === 1);

  // 2. the three settings.
  await session.eval(`(() => {
    const input = [...document.querySelectorAll('${row} label')].find((l) => l.textContent.trim() === "Label new issues");
    const field = document.getElementById(input.htmlFor);
    field.focus();
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(field, "alert");
    field.dispatchEvent(new Event("input", { bubbles: true }));
    field.blur();
  })()`);
  await session.eval(`document.querySelector('[data-comment-updates="${tag}"]').click()`);
  const selectId = await session.eval(`(() => { const l = [...document.querySelectorAll('${row} label')].find((x) => x.textContent.trim() === "When resolved, move the issue to"); return l?.htmlFor ?? null; })()`);
  await waitFor(session, `!document.getElementById(${JSON.stringify(selectId)})?.disabled`);
  await session.click(`#${selectId}`);
  await session.click('[role="option"]', new Function("text", `return text.trim() === ${JSON.stringify(target.name)}`));
  const saved = await waitFor(session, `(async () => { ${PAGE_API}
    const rows = (await api("GET", "/alertmanager/receivers")).body;
    const mine = rows.find((r) => r.name === ${JSON.stringify(tag)});
    return mine && mine.label === "alert" && mine.comment_updates && mine.resolve_state_id === ${JSON.stringify(target.id)} ? mine : null;
  })()`);
  check("label, comment switch and resolve state all saved", Boolean(saved), JSON.stringify(saved));
  check("the page shows what was saved", await waitFor(session, `document.querySelector('[data-comment-updates="${tag}"]')?.getAttribute("aria-checked") === "true"`));
  await sleep(1500);
  const settled = await session.eval(`(() => { const b = document.querySelector('[data-comment-updates="${tag}"]');
    return { checked: b?.getAttribute("aria-checked"), knob: b?.querySelector("span span")?.className, html: b?.outerHTML?.slice(0, 300) }; })()`);
  check("the switch still reads on after the page settles", settled.checked === "true", JSON.stringify(settled));
  await session.screenshot(outputPath("alertmanager-settings-proof.png"));

  // 3. real deliveries.
  const delivered = await session.eval(`(async () => {
    const url = "/api/v1/integrations/alertmanager?token=" + ${JSON.stringify(world.token)};
    const alert = (status) => ({ alerts: [{ status, fingerprint: ${JSON.stringify(tag)}, labels: { alertname: "ProofAlert" }, annotations: { summary: "proof" } }] });
    const send = async (status) => (await fetch(url, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(alert(status)) })).json();
    return [await send("firing"), await send("firing"), await send("resolved")];
  })()`);
  check("deliveries report the receiver's actions",
    delivered[1].commented === 1 && delivered[2].commented === 1 && delivered[2].moved === 1, JSON.stringify(delivered));
  const issue = await session.eval(`(async () => { ${PAGE_API}
    const found = (await api("GET", "/items?project_id=" + ${JSON.stringify(world.projectId)})).body;
    const item = (found.items ?? found)[0];
    const full = (await api("GET", "/items/by-key/" + item.key)).body;
    const comments = (await api("GET", "/items/" + item.id + "/comments")).body;
    return { labels: full.labels, state: full.state?.id ?? full.state_id, comments: (comments.items ?? comments).map((c) => [c.body, c.visibility]) };
  })()`);
  check("the issue is labelled, commented internally and moved", JSON.stringify(issue.labels).includes("alert")
    && issue.state === target.id && issue.comments.length === 2 && issue.comments.every(([, v]) => v === "internal"),
    JSON.stringify(issue));
} finally {
  // 4. clean up.
  if (world?.receiverId) {
    const cleaned = await session.eval(`(async () => { ${PAGE_API}
      const r = await api("DELETE", "/alertmanager/receivers/" + ${JSON.stringify(world.receiverId)});
      const p = await api("DELETE", "/projects/" + ${JSON.stringify(world.projectId)});
      return [r.status, p.status];
    })()`);
    check("the receiver and project are deleted again", cleaned.join() === "204,204", JSON.stringify(cleaned));
  }
  await close();
}
finish({ proof: "alertmanager settings" });

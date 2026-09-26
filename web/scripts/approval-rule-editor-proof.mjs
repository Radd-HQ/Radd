/**
 * Browser proof for RADD-1383: "Require approval" on a workflow transition is the
 * approvals plugin's editor, contributed into the rule slot workflow's UI package
 * publishes, and the gate it writes is enforced through the kernel socket — all
 * against the REAL backend.
 *
 *   1. a throwaway project (guarded transitions, one "Any state → Done" row), a
 *      throwaway team and an issue (API);
 *   2. on Project settings → Workflow, tick "Require approval" (seeds the signed-in
 *      admin) and add the team through the remote's team picker;
 *   3. reload: the rule persisted with both approvers, and the editor came from
 *      the approvals remote (/plugins/approvals/), not the host bundle;
 *   4. a move to Done without an approval is refused with the approval sentence;
 *   5. no console errors; the project and team are deleted again.
 *
 * Usage: node scripts/approval-rule-editor-proof.mjs <baseUrl> [email] [password]
 */
import { resolve } from "node:path";
import { outputPath, PAGE_API, sleep, waitFor } from "./lib/cdp.mjs";
import { startProof } from "./lib/proof.mjs";

const tag = Date.now().toString(36);
const key = `AR${tag.slice(-4).toUpperCase()}`;
const teamName = `Approvers ${tag}`;

const { session, close, check, finish, baseUrl } = await startProof({
  port: 9507, profile: resolve(process.env.TMPDIR || "/tmp", "radd-approval-rule-proof-profile"),
});
let world = null;
try {
  // 1. the world.
  world = await session.eval(`(async () => { ${PAGE_API}
    const me = (await api("GET", "/auth/me")).body;
    const project = await api("POST", "/projects", { key: ${JSON.stringify(key)}, name: "Approval rule proof" });
    const id = project.body.id;
    const mode = await api("PUT", "/scoped-settings", { scope: "project", scope_id: id, key: "workflow_transition_mode", value: "guards" });
    const states = (await api("GET", "/states?project_id=" + id)).body;
    const done = states.find((s) => s.name === "Done");
    const transition = await api("POST", "/transitions", { project_id: id, from_state_id: null, to_state_id: done.id });
    const team = await api("POST", "/teams", { name: ${JSON.stringify(teamName)} });
    const item = await api("POST", "/items", { project_id: id, title: "Needs a sign-off" });
    return { me: { id: me.id, name: me.name }, projectId: id, doneId: done.id, transitionId: transition.body?.id,
      teamId: team.body?.id, itemId: item.body?.id,
      status: [project.status, mode.status, transition.status, team.status, item.status] };
  })()`);
  check("a throwaway project, guarded transition, team and issue exist",
    world.status.join() === "201,200,201,201,201", JSON.stringify(world.status));

  // 2. the editor.
  session.consoleErrors.length = 0;
  await session.navigate(`${baseUrl}/p/${key}/settings/workflow`, 1500);
  const box = `Array.from(document.querySelectorAll('[data-approval-rule] label')).find((l) => l.textContent.trim() === "Require approval")?.querySelector("input")`;
  check("the rule editor offers Require approval", await waitFor(session, `Boolean(${box}) && !${box}.disabled`));
  await session.click("[data-approval-rule] label", (text) => text.trim() === "Require approval");
  check("ticking it seeds the signed-in admin",
    await waitFor(session, `Boolean(document.querySelector('[data-approver="${world.me.id}"]'))`));
  await waitFor(session, `!document.querySelector('[aria-label="Add a team as approver"]')?.disabled`);
  await session.click('[aria-label="Add a team as approver"]');
  await waitFor(session, `Boolean(document.querySelector('[role="dialog"] input'))`);
  await session.eval(`(() => {
    const input = document.querySelector('[role="dialog"] input');
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, ${JSON.stringify(teamName)});
    input.dispatchEvent(new Event("input", { bubbles: true }));
  })()`);
  const offered = await waitFor(session, `[...document.querySelectorAll('[role="dialog"] button')].some((b) => b.textContent.trim() === ${JSON.stringify(teamName)})`);
  check("the remote's team picker offers the team", offered);
  if (offered) await session.click('[role="dialog"] button', new Function("text", `return text.trim() === ${JSON.stringify(teamName)}`));
  const saved = await waitFor(session, `(async () => { ${PAGE_API}
    const rows = (await api("GET", "/projects/${world.projectId}/transitions")).body;
    const rule = rows.find((t) => t.id === "${world.transitionId}")?.rules.find((r) => r.check === "require_approval");
    const ids = (rule?.params.approvers ?? []).map((a) => a.kind + ":" + a.id + ":" + a.name + ":" + (a.required ?? ""));
    return ids.length === 2 ? ids : null;
  })()`);
  check("the rule saved with both approvers, names snapshotted server-side",
    JSON.stringify(saved) === JSON.stringify([`user:${world.me.id}:${world.me.name}:`, `team:${world.teamId}:${teamName}:1`]),
    JSON.stringify(saved));

  // 3. reload: persisted, and the editor is the remote's.
  await session.navigate(`${baseUrl}/p/${key}/settings/workflow`, 1500);
  check("after a reload the editor shows both approvers", await waitFor(session,
    `Boolean(document.querySelector('[data-approver="${world.me.id}"]')) && Boolean(document.querySelector('[data-approver="${world.teamId}"]')) && ${box}?.checked === true`));
  const origin = await session.eval(`({
    fetched: performance.getEntriesByType("resource").some((e) => new URL(e.name).pathname === "/plugins/approvals/remoteEntry.js"),
    active: globalThis.__RADD_SHARED__["@radd/plugin-sdk"].activeSlotPlugins().includes("approvals"),
  })`);
  check("the approver editor came from the approvals remote", origin.fetched && origin.active, JSON.stringify(origin));
  await session.eval(`document.querySelector('[data-approval-rule]').scrollIntoView({ block: "center" })`);
  await sleep(300);
  await session.screenshot(outputPath("approval-rule-editor-proof.png"));

  // 4. the gate holds.
  const move = await session.eval(`(async () => { ${PAGE_API}
    return api("PATCH", "/items/${world.itemId}", { state_id: "${world.doneId}" }); })()`);
  check("a move without approval is refused with the approval message",
    move.status === 422 && move.body.errors?.includes(`approval required (${world.me.name}; 1 of ${teamName})`),
    JSON.stringify(move));

  // 5. a clean console.
  check("no console errors", session.consoleErrors.length === 0, JSON.stringify(session.consoleErrors));
} finally {
  if (world?.projectId) {
    const cleaned = await session.eval(`(async () => { ${PAGE_API}
      const p = await api("DELETE", "/projects/${world.projectId}");
      const t = ${world.teamId ? `(await api("DELETE", "/teams/${world.teamId}")).status` : "null"};
      return [p.status, t];
    })()`);
    check("the project and team are deleted again", cleaned.join() === "204,204", JSON.stringify(cleaned));
  }
  await close();
}
finish({ proof: "approval rule editor" });

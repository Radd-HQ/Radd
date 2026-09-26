/**
 * Browser proof for RADD-1378: Settings → Email is the mailintake plugin's own
 * page, loaded from its remote, against the REAL backend.
 *
 *   1. the host carries no email page: no `email-*` chunk in web/dist, no page
 *      copy in any host asset, and the copy IS in the mailintake remote;
 *   2. a throwaway project + a DISABLED webhook source landing in it (API);
 *   3. the Server group lists Email once, from the plugin's manifest, and the
 *      page renders its four sections, the source row and the three
 *      automatic-message settings (the SDK's ScopedSettings);
 *   4. the page was fetched from /plugins/mailintake/, never a host chunk;
 *   5. the source dialog resolves its default project through the projects
 *      plugin's picker, and a rename saves (read back over the API);
 *   6. the project's delete blocker links to the page through the owner's
 *      entity link, and Server status's Email row links to it too;
 *   7. the source is deleted through the page, then the project over the API.
 *
 * Usage: node scripts/email-settings-page-proof.mjs <baseUrl> [email] [password]
 */
import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { PAGE_API, waitFor } from "./lib/cdp.mjs";
import { startProof } from "./lib/proof.mjs";

const TMP = process.env.TMPDIR || "/tmp";
const stamp = Date.now().toString(36);
const key = `ES${stamp.slice(-4).toUpperCase()}`;
const sourceName = `Email proof ${stamp}`;
const renamed = `${sourceName} renamed`;
const KEYS = ["mail_send_ack", "mail_ack_body", "mail_send_resolved"];
const PAGE_COPY = "Where mail arrives, where it is sent from";

/** Type into the dialog field whose label reads `label`, the way React sees typing. */
const typeInto = (session, label, value) => session.eval(`(() => {
  const dialog = document.querySelector('[role="dialog"]');
  const found = [...dialog.querySelectorAll("label")].find((l) => l.textContent.trim() === ${JSON.stringify(label)});
  const field = found && document.getElementById(found.htmlFor);
  if (!field) return false;
  field.focus();
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(field, ${JSON.stringify(value)});
  field.dispatchEvent(new Event("input", { bubbles: true }));
  return true;
})()`);

const { session, close, check, finish, baseUrl } = await startProof({
  port: 9501, profile: resolve(TMP, "radd-email-settings-page-proof-profile"),
});

// 1. the build: the page is in the remote, and nowhere in the host.
const web = fileURLToPath(new URL("..", import.meta.url));
const assets = readdirSync(resolve(web, "dist/assets"));
check("the host build has no email chunk", !assets.some((file) => /^email[-.]/i.test(file)), assets.filter((f) => /email/i.test(f)).join());
const hostCopy = assets.filter((file) => file.endsWith(".js"))
  .filter((file) => readFileSync(resolve(web, "dist/assets", file), "utf8").includes(PAGE_COPY));
check("no host asset carries the page's copy", hostCopy.length === 0, hostCopy.join());
const remote = readFileSync(resolve(web, "../server/src/radd/modules/mailintake/ui/dist/remoteEntry.js"), "utf8");
check("the mailintake remote does", remote.includes(PAGE_COPY));

let world = null;
try {
  // 2. the world: a project, and a source that is off (nothing polls or accepts it).
  world = await session.eval(`(async () => { ${PAGE_API}
    const project = await api("POST", "/projects", { key: ${JSON.stringify(key)}, name: "Email proof project" });
    const source = await api("POST", "/mail/sources", { name: ${JSON.stringify(sourceName)}, kind: "webhook", enabled: false,
      address: ${JSON.stringify(`${stamp}@example.test`)}, default_project_id: project.body.id, secret: "proof" });
    return { projectId: project.body?.id, sourceId: source.body?.id, status: [project.status, source.status] };
  })()`);
  check("a throwaway project and disabled source exist", world.sourceId && world.status.join() === "201,201", JSON.stringify(world.status));

  // 3. the page.
  await session.navigate(`${baseUrl}/settings/email`, 1500);
  const row = `[data-mail-source="${world.sourceId}"]`;
  check("the page lists the source", await waitFor(session, `Boolean(document.querySelector('${row}'))`));
  const nav = await session.eval(`(() => {
    const links = [...document.querySelectorAll('nav[aria-label="Settings sections"] a')];
    const email = links.filter((a) => a.textContent.trim() === "Email");
    const server = [...document.querySelectorAll('nav[aria-label="Settings sections"] section[aria-label="Server"] a')].map((a) => a.textContent.trim());
    return { count: email.length, href: email[0]?.getAttribute("href"), server };
  })()`);
  check("the Server group lists Email once, linking to the page",
    nav.count === 1 && nav.href === "/settings/email" && nav.server.includes("Email"), JSON.stringify(nav));
  check("…right after Storage, where the host entry was",
    nav.server.indexOf("Email") === nav.server.indexOf("Storage") + 1, nav.server.join(" · "));
  const page = await waitFor(session, `(() => {
    const root = document.querySelector("[data-email-settings]");
    if (!root) return null;
    const headings = [...root.querySelectorAll("h2, h3")].map((h) => h.textContent.trim());
    const settings = ${JSON.stringify(KEYS)}.filter((k) => root.querySelector('[data-automatic-messages] [data-setting="' + k + '"]'));
    return settings.length === ${KEYS.length} ? { headings, settings } : null;
  })()`);
  check("the page renders Incoming, Outgoing, signatures and automatic messages",
    page && ["Incoming", "Outgoing", "Signature detection", "Automatic messages"].every((h) => page.headings.includes(h)), JSON.stringify(page));
  check("…with the three email settings through ScopedSettings", page?.settings.length === KEYS.length, JSON.stringify(page?.settings));

  // 4. where the code came from.
  const loaded = await session.eval(`performance.getEntriesByType("resource").map((e) => new URL(e.name).pathname)`);
  check("the page was loaded from the mailintake remote", loaded.some((p) => p.startsWith("/plugins/mailintake/")),
    loaded.filter((p) => p.startsWith("/plugins/")).join());
  check("…and never from a host email chunk", !loaded.some((p) => /\/assets\/email[-.]/i.test(p)),
    loaded.filter((p) => /email/i.test(p)).join());
  await session.screenshot(resolve(TMP, "email-settings-page-proof.png"));

  // 5. the source dialog: the project picker and one save.
  await session.click(`${row} button`, (text) => text.trim() === "Edit");
  const dialog = await waitFor(session, `(() => {
    const d = document.querySelector('[role="dialog"]');
    return d && /Edit /.test(d.innerText) ? d.innerText : null;
  })()`);
  check("the source dialog opens", Boolean(dialog));
  check("its default project resolves through the projects plugin's picker",
    await waitFor(session, `[...document.querySelectorAll('[role="dialog"] button')].some((b) => b.textContent.includes(${JSON.stringify(`${key} · Email proof project`)}))`),
    String(dialog).slice(0, 300));
  check("the name field takes typing", await typeInto(session, "Name", renamed));
  await session.click('[role="dialog"] button', (text) => text.trim() === "Save");
  const saved = await waitFor(session, `(async () => { ${PAGE_API}
    const mine = (await api("GET", "/mail/sources")).body.find((s) => s.id === ${JSON.stringify(world.sourceId)});
    return mine && mine.name === ${JSON.stringify(renamed)} ? mine : null;
  })()`);
  check("the rename saved (read back over the API)", Boolean(saved), JSON.stringify(saved)?.slice(0, 200));
  check("…closing the dialog and updating the row", await waitFor(session,
    `!document.querySelector('[role="dialog"]') && document.querySelector('${row}')?.innerText.includes(${JSON.stringify(renamed)})`));
  check("…without touching the rest of the row",
    saved?.enabled === false && saved?.default_project_id === world.projectId && saved?.has_secret === true, JSON.stringify(saved)?.slice(0, 200));

  // 6. the two host links into the page, neither naming it.
  const content = await session.eval(`(async () => { ${PAGE_API}
    return (await api("GET", "/projects/" + ${JSON.stringify(world.projectId)} + "/content")).body; })()`);
  const blocker = content?.blockers?.find((b) => b.id === world.sourceId);
  check("the project's delete blocker links to the page by the owner's entity link",
    blocker?.kind === "mail_source" && blocker?.url === "/settings/email", JSON.stringify(content?.blockers));
  await session.navigate(`${baseUrl}/settings/instance`, 1500);
  check("Server status's Email row links to the page", await waitFor(session,
    `[...document.querySelectorAll("a")].some((a) => a.innerText.startsWith("Email") && a.getAttribute("href") === "/settings/email")`));

  // 7. delete the source through the page.
  await session.navigate(`${baseUrl}/settings/email`, 1500);
  await waitFor(session, `Boolean(document.querySelector('${row}'))`);
  await session.click(`${row} button`, (text) => text.trim() === "Edit");
  await waitFor(session, `Boolean(document.querySelector('[role="dialog"]'))`);
  await session.click('[role="dialog"] button', (text) => text.trim() === "Delete");
  await waitFor(session, `[...document.querySelectorAll('[role="dialog"] button')].some((b) => b.textContent.trim() === "Delete source")`);
  await session.click('[role="dialog"] button', (text) => text.trim() === "Delete source");
  const gone = await waitFor(session, `(async () => { ${PAGE_API}
    return !(await api("GET", "/mail/sources")).body.some((s) => s.id === ${JSON.stringify(world.sourceId)}); })()`);
  check("the source is deleted through the page", gone);
  if (gone) world.sourceId = null;
  check("…and its row leaves the list", await waitFor(session, `!document.querySelector('${row}')`));
  check("no console errors", session.consoleErrors.length === 0, session.consoleErrors.slice(0, 3).join(" | "));
} finally {
  if (world?.projectId) {
    const cleaned = await session.eval(`(async () => { ${PAGE_API}
      const s = ${JSON.stringify(world.sourceId)} ? (await api("DELETE", "/mail/sources/" + ${JSON.stringify(world.sourceId)})).status : 204;
      const p = (await api("DELETE", "/projects/" + ${JSON.stringify(world.projectId)})).status;
      return [s, p];
    })()`);
    check("the throwaway source and project are gone again", cleaned.join() === "204,204", JSON.stringify(cleaned));
  }
  await close();
}
finish({ proof: "email settings page", key, source: sourceName });

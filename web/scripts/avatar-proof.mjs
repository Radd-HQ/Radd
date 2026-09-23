#!/usr/bin/env node
/**
 * Proof for RADD-1295 (GitHub radd-hq/radd#18): a person can have a real
 * profile picture.
 *
 *   node web/scripts/avatar-proof.mjs http://127.0.0.1:8000 admin@example.com change-me
 *
 * A throwaway account (the dev admin's avatar is never touched):
 *   1. uploads a 1200×800 image through the real Profile page file input;
 *   2. the top bar shows it — as a picture, loaded, not the initials;
 *   3. what the browser fetched is the NORMALISED picture (256px WebP), not
 *      the upload — measured from the network, not assumed;
 *   4. the admin, looking at an issue assigned to that person, sees the same
 *      face on the assignee field (a different reader, a different surface);
 *   5. Remove picture falls back to the initials.
 * The account and the fixture project are deleted at the end.
 */
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { clickAt, openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
if (!baseUrl || !adminEmail || !adminPassword) {
  console.error("usage: avatar-proof.mjs <baseUrl> <adminEmail> <adminPassword>");
  process.exit(2);
}
const PORT = 9499;
const TMP = process.env.TMPDIR || "/tmp";
const PROFILE = resolve(TMP, "radd-avatar-proof");
const SHOTS = resolve(TMP, "radd-avatar-proof-shots");
const STAMP = Date.now().toString(36).slice(-5);
const KEY = `AV${STAMP.slice(-4).toUpperCase()}`;
const PERSON = `avatar-${STAMP}@example.test`;
const PASSWORD = "avatar-proof-pass-1";
const SOURCE = resolve(TMP, "radd-avatar-proof-source.png");

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

/** The first avatar inside `scope`: what it renders and what it loaded. */
const avatarIn = (scope) => `(() => {
  const avatar = document.querySelector(${JSON.stringify(scope)});
  const img = avatar?.querySelector("img");
  return avatar ? { kind: avatar.getAttribute("data-avatar"), src: img?.getAttribute("src") ?? null,
    loaded: !!img && img.complete && img.naturalWidth > 0, natural: img ? [img.naturalWidth, img.naturalHeight] : null } : null;
})()`;

async function main() {
  execFileSync("mkdir", ["-p", SHOTS]);
  // A photo-sized source, so "normalised" is a measurable claim.
  execFileSync("python3", ["-c",
    `from PIL import Image, ImageDraw
i = Image.new("RGB", (1200, 800), (30, 90, 160)); d = ImageDraw.Draw(i)
d.ellipse((400, 150, 800, 650), fill=(240, 200, 150))
i.save(${JSON.stringify(SOURCE)})`]);

  const { session, close } = await openBrowser({ port: PORT, profile: PROFILE, width: 1400, height: 950, scale: 2 });
  const send = session.send;
  const checks = {};
  const context = {};
  let fixture = null;
  const loginAs = async (email, password) => {
    await session.eval(`fetch("/api/v1/auth/logout", { method: "POST" })`);
    return session.login(baseUrl, email, password);
  };
  try {
    await session.navigate(baseUrl + "/login", 800);
    await session.login(baseUrl, adminEmail, adminPassword);
    fixture = await session.eval(`(async () => { ${API}
      const person = await api("POST", "/users", { email: ${JSON.stringify(PERSON)}, name: "Pictured Person", password: ${JSON.stringify(PASSWORD)} });
      const project = await api("POST", "/projects", { key: ${JSON.stringify(KEY)}, name: "Avatar proof" });
      const item = await api("POST", "/items", { project_id: project.body.id, title: "A parent" });
      await api("POST", "/items", { project_id: project.body.id, title: "Assigned to a face", kind: "subtask", parent_id: item.body.id, assignee_id: person.body.id });
      return { person: person.body, project: project.body, item: item.body };
    })()`);

    // 1 — upload through the real Profile page.
    await loginAs(PERSON, PASSWORD);
    await session.navigate(baseUrl + "/settings/profile", 2500);
    await send("DOM.enable");
    const { root } = await send("DOM.getDocument", { depth: -1, pierce: true });
    const { nodeId } = await send("DOM.querySelector", { nodeId: root.nodeId, selector: "[data-profile-picture] input[type=file]" });
    await send("DOM.setFileInputFiles", { nodeId, files: [SOURCE] });
    await sleep(3000);
    const me = await session.eval(`(async () => (await (await fetch("/api/v1/auth/me")).json()).avatar_url)()`);
    context.avatarUrl = me;
    checks["1. the upload is recorded as the person's picture"] = typeof me === "string" && me.includes(`/users/${fixture.person.id}/avatar?v=`);

    // 2 — the top bar renders it as a loaded picture.
    await session.navigate(baseUrl + "/", 2500);
    const topBar = await session.eval(avatarIn("[data-avatar]"));
    context.topBar = topBar;
    checks["2. the top bar shows the picture, loaded"] = topBar?.kind === "picture" && topBar.loaded;

    // 3 — what was served is the normalised picture, measured from the wire.
    const served = await session.eval(`(async () => {
      const r = await fetch(${JSON.stringify(me)});
      const bytes = (await r.arrayBuffer()).byteLength;
      return { type: r.headers.get("content-type"), bytes, cache: r.headers.get("cache-control") };
    })()`);
    context.served = { ...served, natural: topBar?.natural };
    checks["3. the browser receives a 256px WebP, not the 1200×800 upload"] =
      served.type === "image/webp" && topBar?.natural?.[0] === 256 && topBar?.natural?.[1] === 256;
    await session.screenshot(resolve(SHOTS, "top-bar.png"));

    // 4 — someone else sees the same face on an issue.
    await loginAs(adminEmail, adminPassword);
    await session.navigate(`${baseUrl}/issues/${fixture.item.key}`, 3500);
    // The Subtasks card is collapsed by default; its rows draw each assignee.
    await clickAt(send, "button", (text) => text.trim().toUpperCase().startsWith("SUBTASKS"));
    await sleep(1500);
    const assignee = await session.eval(`(() => {
      const found = [...document.querySelectorAll("[data-avatar=picture] img")]
        .find((img) => img.getAttribute("src") === ${JSON.stringify(me)});
      return found ? { loaded: found.complete && found.naturalWidth > 0, box: found.getBoundingClientRect().width } : null;
    })()`);
    context.assignee = assignee;
    checks["4. another reader sees the face on a subtask's assignee"] = !!assignee?.loaded;
    await session.screenshot(resolve(SHOTS, "issue.png"));

    // 5 — remove it: back to the initials.
    await loginAs(PERSON, PASSWORD);
    await session.navigate(baseUrl + "/settings/profile", 2500);
    await clickAt(send, "[data-profile-picture] button", (text) => text.includes("Remove picture"));
    await sleep(2000);
    const after = await session.eval(`(async () => (await (await fetch("/api/v1/auth/me")).json()).avatar_url)()`);
    const topAfter = await session.eval(avatarIn("[data-avatar]"));
    context.afterRemove = { after, kind: topAfter?.kind };
    checks["5. removing it falls back to the initials"] = after === null && topAfter?.kind === "initials";
    await session.screenshot(resolve(SHOTS, "profile-removed.png"));
  } finally {
    if (fixture) {
      await loginAs(adminEmail, adminPassword).catch(() => null);
      context.cleanup = await session.eval(`(async () => { ${API}
        return {
          project: (await api("DELETE", "/projects/${fixture.project.id}")).status,
          person: (await api("DELETE", "/users/${fixture.person.id}")).status,
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

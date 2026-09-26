/**
 * Browser proof for RADD-1368: Settings → Email's "Automatic messages" panel
 * renders the desk's own messages as settings again.
 *
 *   1. the panel carries the three `email`-section rows — the receipt switch,
 *      the receipt text (a TEXTAREA: `multiline` travels from the SettingSpec),
 *      and the resolution-notice switch — and both switches start OFF;
 *   2. ticking the receipt switch writes the override (read back over the API);
 *   3. the textarea autosaves on blur and keeps its line breaks;
 *   4. every override this proof wrote is removed again, so the instance ends
 *      where it started.
 *
 * Usage: node scripts/email-automatic-messages-proof.mjs <baseUrl> [email] [password]
 */
import { resolve } from "node:path";
import { outputPath, waitFor } from "./lib/cdp.mjs";
import { startProof } from "./lib/proof.mjs";

const KEYS = ["mail_send_ack", "mail_ack_body", "mail_send_resolved"];

const instanceRows = (session) => session.eval(`(async () => {
  const r = await fetch("/api/v1/scoped-settings?scope=instance");
  const rows = await r.json();
  return Object.fromEntries(rows.filter((row) => ${JSON.stringify(KEYS)}.includes(row.key))
    .map((row) => [row.key, { value: row.value, set_here: row.set_here, multiline: row.multiline }]));
})()`);

const { session, close, check, finish, baseUrl } = await startProof({
  port: 9481, profile: resolve(process.env.TMPDIR || "/tmp", "radd-email-messages-proof-profile"),
});
let before = {};
try {
  before = await instanceRows(session);
  check("the API serves the three email settings, receipt text marked multiline",
    KEYS.every((key) => key in before) && before.mail_ack_body.multiline === true, JSON.stringify(before));

  await session.navigate(`${baseUrl}/settings/email`, 1500);
  const rows = await waitFor(session, `(() => {
    const panel = document.querySelector("[data-automatic-messages]");
    if (!panel) return null;
    const found = ${JSON.stringify(KEYS)}.map((key) => {
      const row = panel.querySelector('[data-setting="' + key + '"]');
      if (!row) return null;
      const box = row.querySelector('input[type="checkbox"]');
      return { key, textarea: Boolean(row.querySelector("textarea")), checked: box ? box.checked : null };
    });
    return found.every(Boolean) ? found : null;
  })()`);
  check("the panel renders all three rows", Array.isArray(rows), JSON.stringify(rows));
  const byKey = Object.fromEntries((rows ?? []).map((row) => [row.key, row]));
  check("the receipt text is a textarea", byKey.mail_ack_body?.textarea === true, JSON.stringify(byKey.mail_ack_body));
  check("both switches start as the instance has them",
    byKey.mail_send_ack?.checked === (String(before.mail_send_ack?.value) === "true")
      && byKey.mail_send_resolved?.checked === (String(before.mail_send_resolved?.value) === "true"),
    JSON.stringify(rows));

  // 2. tick the receipt switch.
  await session.eval(`document.querySelector('[data-setting="mail_send_ack"] input[type="checkbox"]').click()`);
  const saved = await waitFor(session, `(async () => {
    const r = await fetch("/api/v1/scoped-settings?scope=instance");
    const row = (await r.json()).find((s) => s.key === "mail_send_ack");
    return row && row.set_here && String(row.value) !== ${JSON.stringify(String(before.mail_send_ack?.value))} ? String(row.value) : null;
  })()`);
  check("ticking the receipt switch writes the override", saved !== null, String(saved));

  // 3. the textarea autosaves on blur, line breaks intact.
  await session.eval(`(() => {
    const area = document.querySelector('[data-setting="mail_ack_body"] textarea');
    area.focus();
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(area, ${JSON.stringify("Thanks {{requester_name}}.\n\nTracked as {{key}}.")});
    area.dispatchEvent(new Event("input", { bubbles: true }));
    area.blur();
  })()`);
  const stored = await waitFor(session, `(async () => {
    const r = await fetch("/api/v1/scoped-settings?scope=instance");
    const row = (await r.json()).find((s) => s.key === "mail_ack_body");
    return row && row.set_here ? row.value : null;
  })()`);
  check("the receipt text autosaves on blur with its line breaks", stored === "Thanks {{requester_name}}.\n\nTracked as {{key}}.", JSON.stringify(stored));
  const height = await session.eval(`document.querySelector('[data-setting="mail_ack_body"] textarea').getBoundingClientRect().height`);
  check("the textarea is tall enough for a paragraph", height >= 90, `${height}px`);
  await session.screenshot(outputPath("email-automatic-messages-proof.png"));
} finally {
  // 4. put the instance back.
  try {
    for (const key of KEYS) {
      if (before[key] && !before[key].set_here) {
        await session.eval(`fetch("/api/v1/scoped-settings?scope=instance&key=${key}", { method: "DELETE" })`);
      } else if (before[key]) {
        await session.eval(`fetch("/api/v1/scoped-settings", { method: "PUT", headers: { "content-type": "application/json" },
          body: JSON.stringify({ scope: "instance", key: ${JSON.stringify(key)}, value: ${JSON.stringify(before[key]?.value)} }) })`);
      }
    }
    const after = await instanceRows(session);
    check("every override this proof wrote is gone again",
      KEYS.every((key) => JSON.stringify(after[key]) === JSON.stringify(before[key])), JSON.stringify(after));
  } finally {
    await close();
  }
}
finish({ proof: "email automatic messages" });

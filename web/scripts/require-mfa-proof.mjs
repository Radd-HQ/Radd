#!/usr/bin/env node
/**
 * Proof for RADD-1279 (require MFA) + RADD-1298 (the enrolment QR),
 * GitHub radd-hq/radd#22 and #21:
 *
 *   node web/scripts/require-mfa-proof.mjs http://127.0.0.1:8000 admin@example.com change-me
 *
 * With throwaway accounts only — the dev admin is never enrolled:
 *   1. an UN-enrolled admin cannot turn `require_mfa` on (the switch's guard);
 *   2. an enrolled throwaway admin can;
 *   3. a member signing in by password lands on enrolment, not the app — and
 *      holds no session there;
 *   4. the QR on that screen DECODES (zbarimg on a screenshot, as a phone
 *      would read it) to the account's otpauth URI;
 *   5. a code derived from the DECODED secret completes enrolment, shows the
 *      recovery codes once, and signs the member in;
 *   6. the Users page shows the member's two-factor as On with a Reset;
 *   7. the Profile panel draws the same QR for self-service setup.
 * The policy is switched back OFF and every account deleted in `finally`.
 */
import { createHmac } from "node:crypto";
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { clickAt, openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
if (!baseUrl || !adminEmail || !adminPassword) {
  console.error("usage: require-mfa-proof.mjs <baseUrl> <adminEmail> <adminPassword>");
  process.exit(2);
}
const PORT = 9497;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-require-mfa-proof");
const SHOTS = resolve(process.env.TMPDIR || "/tmp", "radd-require-mfa-proof-shots");
const STAMP = Date.now().toString(36).slice(-6);
const PASSWORD = "mfa-proof-pass-1";
const GATE_ADMIN = `mfa-gate-${STAMP}@example.test`;
const MEMBER = `mfa-member-${STAMP}@example.test`;

/** RFC 6238, SHA-1/30s/6 — the profile `auth/totp.py` implements. */
function totpCode(secret) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of secret.replace(/=+$/, "").toUpperCase()) {
    bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  }
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 1000 / 30)));
  const digest = createHmac("sha1", key).update(counter).digest();
  const offset = digest[digest.length - 1] & 0x0f;
  const value = digest.readUInt32BE(offset) & 0x7fffffff;
  return String(value % 1_000_000).padStart(6, "0");
}

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

async function main() {
  execFileSync("mkdir", ["-p", SHOTS]);
  const { session, close } = await openBrowser({ port: PORT, profile: PROFILE, width: 1300, height: 950, scale: 2 });
  const send = session.send;
  let gateSecret = "";
  const checks = {};
  const context = { gateAdmin: GATE_ADMIN, member: MEMBER };
  const ids = {};
  const signInAs = async (email, password) => {
    await session.eval(`fetch("/api/v1/auth/logout", { method: "POST" })`);
    return session.login(baseUrl, email, password);
  };
  try {
    await session.navigate(baseUrl + "/login", 800);
    context.adminLogin = await session.login(baseUrl, adminEmail, adminPassword);

    // Two throwaway accounts, created by the dev admin.
    const made = await session.eval(`(async () => { ${API}
      const gate = await api("POST", "/users", { email: ${JSON.stringify(GATE_ADMIN)}, name: "MFA gate admin", password: ${JSON.stringify(PASSWORD)}, instance_role: "admin" });
      const member = await api("POST", "/users", { email: ${JSON.stringify(MEMBER)}, name: "MFA proof member", password: ${JSON.stringify(PASSWORD)} });
      return { gate: gate.body, member: member.body };
    })()`);
    ids.gate = made.gate.id;
    ids.member = made.member.id;

    // 1 — the gate admin, NOT enrolled, is refused the switch.
    await signInAs(GATE_ADMIN, PASSWORD);
    const refused = await session.eval(`(async () => { ${API}
      return api("PUT", "/scoped-settings", { key: "require_mfa", scope: "instance", scope_id: null, value: true });
    })()`);
    checks["1. an un-enrolled admin cannot turn require_mfa on (409)"] =
      refused.status === 409 && /set up two-factor/.test(refused.body?.detail ?? "");

    // 2 — enrol the gate admin over the self-service API, then flip it.
    const flipped = await session.eval(`(async () => { ${API}
      return (await api("POST", "/auth/totp/setup")).body;
    })()`);
    gateSecret = flipped.secret;
    await session.eval(`(async () => { ${API}
      return api("POST", "/auth/totp/confirm", { code: ${JSON.stringify(totpCode(flipped.secret))} });
    })()`);
    const on = await session.eval(`(async () => { ${API}
      return api("PUT", "/scoped-settings", { key: "require_mfa", scope: "instance", scope_id: null, value: true });
    })()`);
    checks["2. an enrolled admin can turn it on"] = on.status === 200 && on.body?.value === true;
    ids.policyOn = on.status === 200;

    // 3 — the member signs in through the real form and lands on enrolment.
    await session.eval(`fetch("/api/v1/auth/logout", { method: "POST" })`);
    await session.navigate(baseUrl + "/login", 1200);
    await clickAt(send, "button", (t) => t.includes("Sign in with a local account"));
    await sleep(300);
    const typeInto = async (label, value) => session.eval(`(() => {
      const input = [...document.querySelectorAll("label")].find((l) => l.textContent.trim().startsWith(${JSON.stringify(label)}))
        ?.parentElement?.querySelector("input") ?? document.querySelector("input[autocomplete=" + ${JSON.stringify(label === "Email" ? "email" : "current-password")} + "]");
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      setter.call(input, ${JSON.stringify(value)});
      input.dispatchEvent(new Event("input", { bubbles: true }));
      return !!input;
    })()`);
    await typeInto("Email", MEMBER);
    await typeInto("Password", PASSWORD);
    await clickAt(send, "form button[type=submit]");
    await sleep(1800);
    const gate = await session.eval(`(async () => ({
      enrolment: !!document.querySelector("[data-mfa-enrollment]"),
      qr: (() => { const q = document.querySelector("[data-totp-qr]"); if (!q) return null;
        const r = q.getBoundingClientRect(); return { w: r.width, h: r.height, bg: getComputedStyle(q).backgroundColor }; })(),
      path: location.pathname,
      // The step's own chrome must fit its card: the first cut sat the QR
      // beside the secret in the 384px sign-in card, crushed the secret field
      // to 12px and pushed Reveal/Copy outside the border.
      fit: (() => {
        const card = document.querySelector("[data-mfa-enrollment]")?.closest(".rounded-lg");
        if (!card) return null;
        const box = card.getBoundingClientRect();
        const spill = [...card.querySelectorAll("input, button, svg")].filter((el) => {
          const r = el.getBoundingClientRect();
          return r.width > 0 && (r.left < box.left - 0.5 || r.right > box.right + 0.5);
        }).map((el) => el.tagName + ":" + (el.textContent || "").trim().slice(0, 12));
        const secret = card.querySelector("[data-copy-value]")?.getBoundingClientRect();
        return { spill, secretWidth: secret ? Math.round(secret.width) : 0 };
      })(),
      me: (await fetch("/api/v1/auth/me")).status,
      meAnonymous: (await (await fetch("/api/v1/auth/me")).json()).anonymous === true,
    }))()`);
    context.gate = gate;
    checks["3a. password sign-in shows enrolment instead of the app"] =
      gate.enrolment && gate.path === "/login";
    checks["3b. no session exists at the enrolment step"] = gate.me === 401 || gate.meAnonymous;
    checks["3c. the QR is drawn at a scannable size on a white tile"] =
      !!gate.qr && gate.qr.w >= 150 && gate.qr.w === gate.qr.h && gate.qr.bg === "rgb(255, 255, 255)";

    checks["3d. the enrolment step fits the sign-in card (nothing spills, secret readable)"] =
      !!gate.fit && gate.fit.spill.length === 0 && gate.fit.secretWidth >= 200;

    // 4 — decode the QR from pixels, as a phone does.
    const shot = resolve(SHOTS, "enrolment.png");
    await session.screenshot(shot);
    let decoded = "";
    try {
      decoded = execFileSync("zbarimg", ["--quiet", "--raw", "-Sdisable", "-Sqrcode.enable", shot]).toString().trim();
    } catch (error) {
      context.zbarError = String(error.stderr || error);
    }
    context.decoded = decoded.replace(/secret=[A-Z2-7]+/, "secret=…");
    const secret = /secret=([A-Z2-7]+)/.exec(decoded)?.[1] ?? "";
    checks["4. the QR decodes to this account's otpauth URI"] =
      decoded.startsWith("otpauth://totp/") && decoded.includes(encodeURIComponent(MEMBER)) && secret.length >= 16;

    // 5 — a code from the DECODED secret completes enrolment and signs in.
    if (secret) {
      await session.eval(`(() => {
        const input = document.querySelector("input[autocomplete=one-time-code]");
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
        setter.call(input, ${JSON.stringify(totpCode(secret))});
        input.dispatchEvent(new Event("input", { bubbles: true }));
      })()`);
      await clickAt(send, "button", (t) => t.includes("Confirm and sign in"));
      await sleep(1500);
      const codes = await session.eval(`(() => ({
        shown: [...document.querySelectorAll("p")].some((p) => p.textContent.includes("Save your recovery codes")),
        count: document.querySelectorAll(".font-mono span").length,
      }))()`);
      await session.screenshot(resolve(SHOTS, "recovery-codes.png"));
      checks["5a. confirming shows the recovery codes once"] = codes.shown && codes.count === 10;
      await clickAt(send, "button", (t) => t.includes("I saved them"));
      await sleep(2500);
      const inside = await session.eval(`(async () => {
        const me = await (await fetch("/api/v1/auth/me")).json();
        return { email: me.email, path: location.pathname };
      })()`);
      context.inside = inside;
      checks["5b. …and the member is signed in, inside the app"] =
        inside.email === MEMBER && inside.path !== "/login";
    }

    // 6 — the Users page, as the gate admin.
    await signInAs(GATE_ADMIN, PASSWORD).catch(() => null);
    // The gate admin is enrolled now, so a password alone is refused — use the code step.
    await session.eval(`(async () => { ${API}
      return api("POST", "/auth/login/totp", { email: ${JSON.stringify(GATE_ADMIN)}, password: ${JSON.stringify(PASSWORD)}, code: ${JSON.stringify(totpCode(flipped.secret))} });
    })()`);
    await session.navigate(baseUrl + "/settings/users", 1500);
    await session.eval(`(() => {
      const input = [...document.querySelectorAll("input")].find((i) => i.placeholder === "Email or name…");
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      setter.call(input, ${JSON.stringify(MEMBER)});
      input.dispatchEvent(new Event("input", { bubbles: true }));
    })()`);
    await sleep(1500);
    const cell = await session.eval(`(() => {
      const row = [...document.querySelectorAll("tr")].find((tr) => tr.textContent.includes(${JSON.stringify(MEMBER)}));
      const c = row?.querySelector("[data-mfa-cell]");
      return c ? { state: c.getAttribute("data-mfa-cell"), reset: [...c.querySelectorAll("button")].some((b) => b.textContent.trim() === "Reset") } : null;
    })()`);
    context.usersCell = cell;
    checks["6. Users shows the member's two-factor On, with Reset"] = cell?.state === "on" && cell.reset;
    await session.screenshot(resolve(SHOTS, "users.png"));

    // Sign-in settings carries the switch, saying what it does not cover.
    await session.navigate(baseUrl + "/settings/sign-in", 1500);
    const policy = await session.eval(`(() => {
      const s = document.querySelector("[data-mfa-policy]");
      return s ? { text: s.textContent } : null;
    })()`);
    checks["6b. Settings → Sign-in shows the switch and names what it does not cover"] =
      !!policy && policy.text.includes("Require two-factor authentication") && /Active Directory, Google, GitHub/.test(policy.text);
    await session.screenshot(resolve(SHOTS, "sign-in-settings.png"));

    // 7 — the Profile panel draws the same QR for self-service setup (the dev admin).
    await session.eval(`(async () => { ${API}
      await api("PUT", "/scoped-settings", { key: "require_mfa", scope: "instance", scope_id: null, value: false });
    })()`);
    ids.policyOn = false;
    await signInAs(adminEmail, adminPassword);
    await session.navigate(baseUrl + "/settings/profile", 1500);
    await clickAt(send, "button", (t) => t.trim() === "Enable" || t.trim() === "Restart setup");
    await sleep(1200);
    const profileQr = await session.eval(`(() => !!document.querySelector("[data-totp-qr]"))()`);
    checks["7. the Profile setup panel draws the QR too"] = profileQr;
    await session.screenshot(resolve(SHOTS, "profile.png"));
    // Abandon it: a pending (unconfirmed) row never gates a login.
  } finally {
    try {
      // With the policy still on, the (un-enrolled) dev admin cannot sign in —
      // the enrolled gate admin switches it off first, through the code step.
      if (ids.policyOn && gateSecret) {
        await session.eval(`(async () => { ${API}
          await fetch("/api/v1/auth/logout", { method: "POST" });
          await api("POST", "/auth/login/totp", { email: ${JSON.stringify(GATE_ADMIN)}, password: ${JSON.stringify(PASSWORD)}, code: ${JSON.stringify(totpCode(gateSecret || "AAAAAAAA"))} });
          await api("PUT", "/scoped-settings", { key: "require_mfa", scope: "instance", scope_id: null, value: false });
        })()`);
      }
      await session.eval(`fetch("/api/v1/auth/logout", { method: "POST" })`);
      await session.login(baseUrl, adminEmail, adminPassword);
      context.cleanup = await session.eval(`(async () => { ${API}
        const off = await api("PUT", "/scoped-settings", { key: "require_mfa", scope: "instance", scope_id: null, value: false });
        const out = { policyOff: off.status };
        for (const id of ${JSON.stringify([ids.gate, ids.member].filter(Boolean))}) {
          out[id] = (await api("DELETE", "/users/" + id)).status;
        }
        return out;
      })()`);
    } catch (error) {
      context.cleanupError = String(error);
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

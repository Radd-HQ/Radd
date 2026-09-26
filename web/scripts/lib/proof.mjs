/** The scaffold a real-backend proof shares: its arguments, a signed-in browser, a check list, and
 *  a report that sets the exit code. */
import { openBrowser, report } from "./cdp.mjs";

/**
 * `<baseUrl> [email] [password]` (or `--base <url>`), each falling back to RADD_PROOF_BASE_URL /
 * RADD_PROOF_EMAIL / RADD_PROOF_PASSWORD, then to the defaults given (the dev stack's by default).
 */
export function proofArgs({ base = "http://127.0.0.1:8000", email = "admin@example.com", password = "change-me" } = {}) {
  const argv = process.argv.slice(2);
  const at = argv.indexOf("--base");
  const [baseArg, emailArg, passwordArg] = at >= 0 ? [argv[at + 1]] : argv;
  return {
    baseUrl: baseArg ?? process.env.RADD_PROOF_BASE_URL ?? base,
    email: emailArg ?? process.env.RADD_PROOF_EMAIL ?? email,
    password: passwordArg ?? process.env.RADD_PROOF_PASSWORD ?? password,
  };
}

/**
 * Open a browser (`openBrowser` options), sign in, and start the check list with the two sign-in
 * checks. `finish(context)` prints the report and exits non-zero on any failure; `close()` first.
 */
export async function startProof({ base, email, password, ...browser }) {
  const args = proofArgs({ base, email, password });
  const { session, close } = await openBrowser(browser);
  const checks = [];
  const check = (name, ok, detail = "") => checks.push({ name, ok: Boolean(ok), detail });
  await session.navigate(`${args.baseUrl}/login`, 800);
  const hoverCapable = await session.hoverCapable();
  const loginStatus = await session.login(args.baseUrl, args.email, args.password);
  check("headless Chrome is hover-capable", hoverCapable);
  check("signed in", loginStatus === 200 || loginStatus === 204, `login → ${loginStatus}`);
  const finish = (context) => process.exit(report(checks, context) ? 1 : 0);
  return { ...args, session, close, check, checks, hoverCapable, loginStatus, finish };
}

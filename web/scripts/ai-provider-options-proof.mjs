/**
 * RADD-1273: the AI provider form carries a Reasoning switch (off by default)
 * and an "Extra request parameters (JSON)" field; both round-trip through the
 * API and show on the providers table. Runs against a local instance that has
 * an OpenAI-shape provider named by RADD_PROOF_PROVIDER (default "VLLM").
 *
 *   node scripts/ai-provider-options-proof.mjs
 *   (defaults: RADD_PROOF_EMAIL / RADD_PROOF_PASSWORD, else admin@example.com / change-me)
 *
 * Leaves the provider as it found it: the parameter it writes is removed at the end.
 */
import { mkdir, writeFile } from "node:fs/promises";
import { openBrowser, sleep } from "./lib/cdp.mjs";

const baseUrl = process.env.RADD_PROOF_BASE_URL || "http://127.0.0.1:8000";
const email = process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = process.env.RADD_PROOF_PASSWORD ?? "change-me";
const providerName = process.env.RADD_PROOF_PROVIDER ?? "VLLM";
const output = process.env.RADD_PROOF_OUTPUT_DIR || "/tmp/radd-ai-provider-options-proof";
await mkdir(output, { recursive: true });

const { session, close } = await openBrowser({ port: 9531, profile: output + "/chrome", width: 1440, height: 1000 });
const checks = {};
const dialogTextarea = '[role=dialog] textarea';
const dialogCheckbox = '[role=dialog] input[type=checkbox]';
const dialogSubmit = '[role=dialog] button[type=submit]';

/** Type into the dialog's textarea the way React sees it (native setter + input event). */
const setTextarea = (text) =>
  session.eval(`(() => {
    const ta = document.querySelector(${JSON.stringify(dialogTextarea)});
    if (!ta) return false;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(ta, ${JSON.stringify(text)});
    ta.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
  })()`);
const providerRow = () =>
  session.eval(`(() => {
    const row = [...document.querySelectorAll("table tbody tr")]
      .find((tr) => tr.querySelector("td")?.textContent.trim().startsWith(${JSON.stringify(providerName)}));
    return row ? row.textContent : null;
  })()`);
const providerFromApi = () =>
  session.eval(`fetch("/api/v1/ai/providers", { credentials: "include" }).then((r) => r.json())
    .then((rows) => rows.find((p) => p.name === ${JSON.stringify(providerName)}))`);
const openEdit = async () => {
  await session.click(`button[aria-label='Edit ${providerName}']`, () => true);
  await sleep(600);
};

try {
  await session.navigate(baseUrl + "/login", 1500);
  checks.hoverCapable = await session.hoverCapable();
  checks.loggedIn = (await session.login(baseUrl, email, password)) === 204;
  await session.navigate(baseUrl + "/settings/ai", 2500);

  const before = await providerFromApi();
  if (!before) throw new Error(`no provider named ${providerName} on ${baseUrl}`);
  checks.apiReadCarriesBothFields = "reasoning" in before && "request_params" in before;
  checks.rowReadsOffByDefault = before.reasoning === false && /Off/.test((await providerRow()) ?? "");

  // --- the form: switch present and unchecked, textarea present, a value saves
  await openEdit();
  checks.dialogOpened = await session.eval('!!document.querySelector("[role=dialog]")');
  checks.reasoningSwitchPresent = await session.eval(`!!document.querySelector(${JSON.stringify(dialogCheckbox)})`);
  checks.reasoningDefaultOff = await session.eval(`!document.querySelector(${JSON.stringify(dialogCheckbox)}).checked`);
  checks.paramsFieldPresent = await setTextarea('{ "temperature": 0.2 }');
  await session.screenshot(output + "/provider-form.png");
  await session.click(dialogSubmit, () => true);
  await sleep(1500);
  const saved = await providerFromApi();
  checks.paramsRoundTrip = saved.request_params?.temperature === 0.2 && saved.reasoning === false;
  checks.rowShowsParamCount = /\+1 param/.test((await providerRow()) ?? "");
  await session.screenshot(output + "/providers-table.png");

  // --- refusals happen in the form, before any request
  await openEdit();
  checks.editShowsStoredParams = await session.eval(
    `document.querySelector(${JSON.stringify(dialogTextarea)}).value.includes("temperature")`,
  );
  await setTextarea("{ oops");
  await session.click(dialogSubmit, () => true);
  await sleep(400);
  checks.invalidJsonRefused = await session.eval(
    '!!document.querySelector("[role=dialog]") && /Not valid JSON/.test(document.querySelector("[role=dialog]").textContent)',
  );
  await setTextarea('{ "messages": [] }');
  await session.click(dialogSubmit, () => true);
  await sleep(400);
  checks.reservedKeyRefused = await session.eval(
    '!!document.querySelector("[role=dialog]") && /Cannot set messages/.test(document.querySelector("[role=dialog]").textContent)',
  );
  await session.screenshot(output + "/provider-form-refused.png");

  // --- clear it again: an empty field is {} and the chip goes away
  await setTextarea("");
  await session.click(dialogSubmit, () => true);
  await sleep(1500);
  const restored = await providerFromApi();
  checks.emptyFieldClears = Object.keys(restored.request_params ?? { x: 1 }).length === 0;
  checks.rowChipGone = !/param/.test((await providerRow()) ?? "");
  checks.noConsoleErrors = session.consoleErrors.length === 0;
  if (!checks.noConsoleErrors) console.error(session.consoleErrors);

  console.log(JSON.stringify(checks, null, 2));
  await writeFile(output + "/browser-checks.json", JSON.stringify(checks, null, 2));
  if (Object.values(checks).some((x) => !x)) throw new Error("Browser check failed");
} finally {
  await close();
}

/**
 * Headless render proof for the frontend module-federation platform (spec 94, LOCKED-3).
 *
 * Proves the whole chain in a REAL browser:
 *   1. host boots, reads /capabilities, imports the participants REMOTE bundle at runtime;
 *   2. the remote's activate() registers into the host's shared slot registry (one singleton);
 *   3. the issue view's <Slot> RENDERS the remote's Participants section into the DOM;
 *   4. the ui_api_version gate accepts a compatible major and refuses an incompatible one;
 *   5. LIVE enable/disable: disabling the plugin removes its section from the DOM without a reload,
 *      re-enabling brings it back.
 *
 * Requires a running Radd server (serving the built web/dist) with the participants plugin enabled
 * and a reachable issue. Usage:
 *   node scripts/render-proof.mjs <baseUrl> <issueKey> <email> <password> [pluginId]
 */
import { resolve } from "node:path";
import { openBrowser, sleep } from "./lib/cdp.mjs";

const [baseUrl, issueKey, email, password, pluginId = "participants"] = process.argv.slice(2);
const sectionSel = `'[data-plugin-section="participants"]'`;

async function main() {
  const { session, close } = await openBrowser({
    port: 9444, profile: resolve(process.env.TMPDIR || "/tmp", "radd-render-proof-profile"),
  });
  await session.navigate(baseUrl + "/", 1200);
  const loginStatus = await session.login(baseUrl, email, password);
  const manifestRemotes = await session.eval(
    `(async()=>(await (await fetch("/api/v1/capabilities",{credentials:"include"})).json()).remotes)()`);

  await session.navigate(`${baseUrl}/issues/${issueKey}`, 0);
  let domFound = false, activePlugins = [], importMap = false;
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    const p = await session.eval(
      `(()=>({dom:!!document.querySelector(${sectionSel}),active:(globalThis.__RADD_SLOT_REGISTRY__&&globalThis.__RADD_SLOT_REGISTRY__.activePlugins)?globalThis.__RADD_SLOT_REGISTRY__.activePlugins():[],importMap:!!document.querySelector('script[type="importmap"]')}))()`);
    activePlugins = p.active; importMap = p.importMap;
    if (p.dom) { domFound = true; break; }
  }

  const uiApiVersionGate = await session.eval(
    `(()=>{const m=globalThis.__RADD_SHARED__&&globalThis.__RADD_SHARED__["@radd/plugin-sdk"];return m?{compatibleMajor:m.isUiApiCompatible("2.0.0"),incompatibleMajor:m.isUiApiCompatible("1.4.0"),version:m.UI_API_VERSION}:null;})()`);

  // LIVE disable → the section must vanish without a reload; then re-enable → it returns.
  async function toggle(action) {
    await session.eval(
      `(async()=>{await fetch("/api/v1/plugins/${pluginId}/${action}",{method:"POST",credentials:"include"});globalThis.__RADD_QUERY_CLIENT__&&globalThis.__RADD_QUERY_CLIENT__.invalidateQueries({queryKey:["capabilities"]});})()`);
  }
  async function waitDom(want) {
    for (let i = 0; i < 30; i++) {
      await sleep(400);
      const present = await session.eval(`!!document.querySelector(${sectionSel})`);
      if (present === want) return true;
    }
    return false;
  }
  await toggle("disable");
  const disappearedOnDisable = await waitDom(false);
  await toggle("enable");
  const reappearedOnEnable = await waitDom(true);

  const result = {
    loginStatus, manifestRemotes, slotRegistryActivePlugins: activePlugins,
    participantsSectionRenderedInDom: domFound, importMapPresent: importMap,
    uiApiVersionGate, liveDisableRemovedSection: disappearedOnDisable,
    liveEnableRestoredSection: reappearedOnEnable, consoleErrors: session.consoleErrors,
  };
  console.log(JSON.stringify(result, null, 2));

  await close();
  const ok = loginStatus === 204 &&
    Array.isArray(manifestRemotes) && manifestRemotes.some((r) => r.name === "participants") &&
    activePlugins.includes("participants") && domFound && importMap &&
    uiApiVersionGate && uiApiVersionGate.compatibleMajor === true && uiApiVersionGate.incompatibleMajor === false &&
    disappearedOnDisable && reappearedOnEnable;
  process.exit(ok ? 0 : 1);
}
main().catch((e) => { console.error("PROOF ERROR:", e); process.exit(2); });

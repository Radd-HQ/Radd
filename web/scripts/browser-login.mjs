/** Login method selection and recovery through the built SPA and real HTTP. */
import assert from "node:assert/strict";
import http from "node:http";
import {readFileSync, existsSync, statSync} from "node:fs";
import {mkdtemp} from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {openBrowser} from "./lib/cdp.mjs";
const dist = fileURLToPath(new URL("../dist/", import.meta.url));
let options = {ldap_enabled: true, sso_enabled: true};
let failOptions = false;
const requests = [];
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://fixture");
  if (url.pathname.startsWith("/api/")) {
    let data = [];
    let status = 200;
    if (url.pathname.endsWith("/login-options")) {data = options; status = failOptions ? 503 : 200;}
    else if (url.pathname.endsWith("/auth/me")) { status = 401; data = {detail: "Sign in"}; }
    else if (url.pathname.endsWith("/sso/providers")) data = options.sso_enabled ? [{id: "google", name: "Google", kind: "google"}, {id: "github", name: "GitHub", kind: "github"}] : [];
    else if (req.method === "POST") {
      let body = ""; for await (const part of req) body += part;
      requests.push({path: url.pathname, body: JSON.parse(body)});
      status = 401; data = {detail: url.pathname.endsWith("/auth/login") ? "totp_required" : "invalid credentials"};
    }
    res.writeHead(status, {"content-type": "application/json"}); res.end(JSON.stringify(data)); return;
  }
  const candidate = path.join(dist, url.pathname);
  const file = existsSync(candidate) && statSync(candidate).isFile() ? candidate : path.join(dist, "index.html");
  const mime = file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : "text/html";
  res.writeHead(200, {"content-type": mime}); res.end(readFileSync(file));
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
let browser;
try {
  browser = await openBrowser({port: 18844, profile: await mkdtemp("/tmp/radd-login-preferences-"), width: 390, height: 844, scale: 1});
  const s = browser.session;
  const visit = () => s.navigate(`http://127.0.0.1:${server.address().port}/login?next=%2Fprojects`);
  const button = async text => {
    await until(() => s.eval(`[...document.querySelectorAll('button')].some(el => el.textContent.trim() === ${JSON.stringify(text)} && !el.disabled)`));
    await s.click("button", new Function("value", `return value.trim() === ${JSON.stringify(text)}`));
  };
  const type = async (selector, text) => {await s.click(selector); await s.send("Input.insertText", {text});};
  const until = async predicate => {
    for (let i=0; i<100; i++) {if (await predicate()) return; await new Promise(r => setTimeout(r, 50));}
    throw new Error("Login condition did not settle");
  };
  await visit();
  assert(await s.eval(`!!document.querySelector('input[placeholder="jdoe"]')`));
  assert.equal(await s.eval(`!!document.querySelector('input[type="email"]')`), false);
  assert(await s.eval(`document.body.innerText.includes('Sign in with a local account')`));
  await type('input[placeholder="jdoe"]', "directory-user");
  await type('input[type="password"]', "directory-password");
  await button("Sign in"); await until(() => requests.length === 1);
  assert.equal(requests[0].path, "/api/v1/auth/ldap/login");
  await button("Sign in with a local account");
  assert.equal(await s.eval(`document.querySelector('input[type="password"]').value`), "");
  await type('input[type="email"]', "admin@example.test");
  await type('input[type="password"]', "local-password");
  await button("Sign in");
  await until(() => s.eval(`!!document.querySelector('input[placeholder="123456"]')`));
  await type('input[placeholder="123456"]', "123456"); await button("Sign in");
  await until(() => requests.length === 3);
  assert.equal(requests[1].path, "/api/v1/auth/login");
  assert.equal(requests[2].path, "/api/v1/auth/login/totp");
  assert.equal(requests[2].body.code, "123456");
  await button("Close local account sign-in");
  await until(() => s.eval(`!document.querySelector('input[placeholder="123456"]')`));
  assert.equal(await s.eval(`document.querySelector('input[type="password"]').value`), "");
  // No tabs; the local link precedes the SSO alternatives in every layout.
  const checkLayout = async () => {
    assert.equal(await s.eval(`!!document.querySelector('[aria-label="Sign-in method"], [role="tablist"]')`), false);
    assert(await s.eval(`document.documentElement.scrollWidth <= innerWidth`));
    if (options.sso_enabled) {
      assert(await s.eval(`document.body.innerText.includes('Sign in with Google') && document.body.innerText.includes('Sign in with GitHub')`));
      assert(await s.eval(`document.querySelector('a[href*="google"]').href.includes('next=%2Fprojects')`));
      assert(await s.eval(`(() => {
        const local = [...document.querySelectorAll('button')].find(b => b.textContent.includes('Sign in with a local account'));
        return local.getBoundingClientRect().bottom < document.querySelector('a[href*="google"]').getBoundingClientRect().top;
      })()`));
    }
  };
  await checkLayout();
  await s.screenshot("/tmp/radd-tabless-directory.png");
  for (const ldap_enabled of [false, true]) for (const sso_enabled of [false, true]) {
    options = {ldap_enabled, sso_enabled}; await visit();
    assert.equal(await s.eval(`!!document.querySelector('input[placeholder="jdoe"]')`), ldap_enabled);
    assert.equal(await s.eval(`!!document.querySelector('input[type="email"]')`), false);
    await checkLayout();
    await button("Sign in with a local account");
    await until(() => s.eval(`!!document.querySelector('input[type="email"]')`));
    assert.equal(await s.eval(`!!document.querySelector('input[placeholder="jdoe"]')`), false);
  }
  options = {ldap_enabled: false, sso_enabled: true}; await visit();
  await s.screenshot("/tmp/radd-tabless-sso.png");
  failOptions = true; await visit();
  assert(await s.eval(`document.body.innerText.includes('Could not load sign-in options')`));
  assert.equal(await s.eval(`!!document.querySelector('input[placeholder="jdoe"]')`), false);
  await button("Sign in with a local account");
  await until(() => s.eval(`!!document.querySelector('input[type="email"]')`));
  console.log("Tabless login: active directory only, local recovery link, separate credentials, TOTP, SSO alternatives, return URL, error recovery and mobile layout passed.");
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}

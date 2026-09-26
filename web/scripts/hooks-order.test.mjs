/**
 * No hook after an early return (RADD-1373). React counts hooks per render; a component that
 * returns early on one render and reaches a later `use…()` on the next throws "Rendered fewer
 * hooks than expected" (#300). The account menu did exactly that — `useAppearance()` sat below
 * two auth-state returns — and it took down every page the moment auth state changed after the
 * first render. There is no ESLint rules-of-hooks in this repo, so this is the check.
 *
 * Scope: every component (`Capitalized`) and hook (`useX`) in the host, the SDK and every plugin
 * UI. A statement containing a `return` (outside nested functions) marks the rest of the body as
 * conditional; any hook call after it, at any depth outside nested functions, is a violation.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { parse } from "@babel/parser";

const repo = new URL("../../", import.meta.url).pathname;
const FUNCTIONS = new Set(["FunctionExpression", "ArrowFunctionExpression", "FunctionDeclaration"]);

function files(root) {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    if (["node_modules", "dist"].includes(entry.name)) return [];
    const name = path.join(root, entry.name);
    return entry.isDirectory() ? files(name) : /\.(ts|tsx)$/.test(name) ? [name] : [];
  });
}

/** Does `node` contain a match, not looking inside nested functions? */
function contains(node, match) {
  if (!node || typeof node !== "object") return false;
  if (Array.isArray(node)) return node.some((child) => contains(child, match));
  if (FUNCTIONS.has(node.type)) return false;
  if (match(node)) return true;
  return Object.values(node).some((value) => value && typeof value === "object" && contains(value, match));
}

const isHook = (node) => node.type === "CallExpression" && (
  (node.callee.type === "Identifier" && /^use[A-Z]/.test(node.callee.name))
  || (node.callee.type === "MemberExpression" && node.callee.object?.name === "React"
    && /^use[A-Z]/.test(node.callee.property?.name ?? "")));
const isReturn = (node) => node.type === "ReturnStatement";

function violations(file) {
  const out = [];
  const check = (fn, name) => {
    if (fn.body?.type !== "BlockStatement") return;
    let conditional = false;
    for (const statement of fn.body.body) {
      if (conditional && contains(statement, isHook)) out.push(`${path.relative(repo, file)}:${statement.loc.start.line} ${name}`);
      if (statement.type !== "ReturnStatement" && contains(statement, isReturn)) conditional = true;
    }
  };
  const ast = parse(readFileSync(file, "utf8"), { sourceType: "module", plugins: ["typescript", "jsx"] });
  (function walk(node) {
    if (!node || typeof node !== "object") return;
    if (Array.isArray(node)) return node.forEach(walk);
    if (node.type === "FunctionDeclaration" && /^([A-Z]|use[A-Z])/.test(node.id?.name ?? "")) check(node, node.id.name);
    if (node.type === "VariableDeclarator" && /^([A-Z]|use[A-Z])/.test(node.id?.name ?? "") && FUNCTIONS.has(node.init?.type)) {
      check(node.init, node.id.name);
    }
    for (const value of Object.values(node)) if (value && typeof value === "object") walk(value);
  })(ast.program);
  return out;
}

test("no component or hook calls a hook after an early return", () => {
  const modules = path.join(repo, "server/src/radd/modules");
  const roots = [
    path.join(repo, "web/src"),
    path.join(repo, "web/packages/plugin-sdk/src"),
    ...readdirSync(modules).map((name) => path.join(modules, name, "ui/src")).filter(existsSync),
  ];
  const found = roots.flatMap((root) => files(root).flatMap(violations));
  assert.deepEqual(found, []);
});

test("the check catches the account-menu shape it was written for", () => {
  const sample = path.join(repo, "web/scripts/fixtures/hook-after-return.tsx");
  assert.equal(violations(sample).length, 1);
});

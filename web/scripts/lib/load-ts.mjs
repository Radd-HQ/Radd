/** Load TypeScript sources in a unit test without a build: types stripped by Node itself. */
import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import { dirname, resolve } from "node:path";

function moduleUrl(file, edit) {
  const source = stripTypeScriptTypes(edit(readFileSync(file, "utf8"))).replace(
    /from "(\.[^"]+)"/g,
    (_match, relative) =>
      `from ${JSON.stringify(moduleUrl(resolve(dirname(file), relative.endsWith(".ts") ? relative : `${relative}.ts`), (s) => s))}`,
  );
  return `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
}

/**
 * Import `file` (relative to the working directory) as an ES module, and its relative imports the
 * same way. `edit` rewrites the source first (e.g. to drop an import that cannot resolve here).
 */
export const importTs = (file, edit = (source) => source) => import(moduleUrl(resolve(file), edit));

/**
 * Evaluate TypeScript `code` as a function body: its imports are dropped and supplied by NAME in
 * `imports`; returns `{ [name]: value }` for each of `names`. For sources whose imports cannot
 * resolve outside the bundler (packages, host aliases).
 */
export function evaluateTs(code, imports, names) {
  const js = stripTypeScriptTypes(code)
    .replace(/^import[\s\S]*?from ["'][^"']+["'];\n/gm, "")
    .replace(/^export \{[^}]+\} from ["'][^"']+["'];\n/gm, "")
    .replaceAll("export ", "");
  return Function(...Object.keys(imports), `${js}; return {${names.join(",")}}`)(...Object.values(imports));
}

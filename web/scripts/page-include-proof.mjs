/**
 * Proof for `radd:include` (RADD-716): transclusion renders the source's CURRENT
 * body, edits to the source propagate, and a cycle is refused rather than
 * recursing until the tab dies.
 *
 * The cycle case is why this is a browser proof and not a unit test: the guard
 * lives in the render stack, and "A includes B, B includes A" is only a loop
 * once you are already inside A.
 *
 * Usage: node scripts/page-include-proof.mjs <baseUrl> <spaceSlug> <email> <password>
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, spaceSlug, email, password] = process.argv.slice(2);

async function main() {
  const { session, close } = await openBrowser({
    port: 9449, profile: resolve(process.env.TMPDIR || "/tmp", "radd-include-proof"),
  });
  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);

  // Three pages: `fragment` (the shared content), `host` (includes it), and
  // `loop-a` / `loop-b` which include each other.
  const built = await session.eval(`(async () => {
    const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
    const space = spaces.find((s) => s.slug === ${JSON.stringify(spaceSlug)});
    const list = async () => (await (await fetch("/api/v1/page-spaces/" + space.id + "/pages", {credentials:"include"})).json());
    const upsert = async (title, slug, body) => {
      const pages = await list();
      const found = pages.find((p) => p.slug === slug);
      if (found) {
        await fetch("/api/v1/pages/" + found.id, { method: "PATCH", credentials: "include",
          headers: {"Content-Type":"application/json"}, body: JSON.stringify({ body }) });
        return found;
      }
      return await (await fetch("/api/v1/pages", { method: "POST", credentials: "include",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ space_id: space.id, title, slug, body }) })).json();
    };
    const fragment = await upsert("Fragment", "inc-fragment", "ORIGINAL FRAGMENT TEXT");
    const host = await upsert("Host", "inc-host", "Before.\\n\\n\`\`\`radd:include\\n{\\"page\\": \\"inc-fragment\\"}\\n\`\`\`\\n\\nAfter.");
    const a = await upsert("Loop A", "inc-loop-a", "\`\`\`radd:include\\n{\\"page\\": \\"inc-loop-b\\"}\\n\`\`\`");
    const b = await upsert("Loop B", "inc-loop-b", "\`\`\`radd:include\\n{\\"page\\": \\"inc-loop-a\\"}\\n\`\`\`");
    return { fragmentId: fragment.id, hostSlug: host.slug, aSlug: a.slug };
  })()`);

  const readBody = async (slug) => {
    await session.navigate(`${baseUrl}/pages/${spaceSlug}/${slug}`, 0);
    for (let i = 0; i < 40; i++) {
      await sleep(500);
      const text = await session.eval(
        `(() => { const b = document.querySelector('[data-page-body]'); return b ? b.textContent : ""; })()`);
      if (text && text.length > 10) return text;
    }
    return "";
  };

  const hostText = await readBody(built.hostSlug);

  // Edit the SOURCE, reload the host: the change must appear.
  await session.eval(`(async () => {
    await fetch("/api/v1/pages/${built.fragmentId}", { method: "PATCH", credentials: "include",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ body: "EDITED FRAGMENT TEXT" }) });
  })()`);
  const hostAfterEdit = await readBody(built.hostSlug);

  // The cycle. If the guard is missing this never settles — so bound it.
  const start = Date.now();
  const loopText = await readBody(built.aSlug);
  const loopMs = Date.now() - start;

  const hoverCapable = await session.hoverCapable();
  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    "the included body renders inside the host": hostText.includes("ORIGINAL FRAGMENT TEXT"),
    "the host's own content still renders": hostText.includes("Before.") && hostText.includes("After."),
    "the include is labelled with its source": hostText.includes("Included from"),
    "editing the source updates the includer": hostAfterEdit.includes("EDITED FRAGMENT TEXT"),
    "the stale text is gone": !hostAfterEdit.includes("ORIGINAL FRAGMENT TEXT"),
    "a cycle renders a message instead of recursing": /loop forever/i.test(loopText),
    "and it settles quickly": loopMs < 25000,
    "no console errors": session.consoleErrors.length === 0,
  };
  const failed = report(checks, { hostText: hostText.slice(0, 220), loopText: loopText.slice(0, 220), loopMs, consoleErrors: session.consoleErrors });
  await close();
  return failed;
}

main()
  .then((f) => process.exit(f ? 1 : 0))
  .catch((e) => { console.error(e); process.exit(2); });

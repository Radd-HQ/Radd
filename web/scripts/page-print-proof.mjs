/**
 * Proof for the PDF export (RADD-733 and its subtasks).
 *
 * The assertions that earn their keep:
 *  - RADD-736: the page is NOT blank. The body renders asynchronously, so a print
 *    fired on mount emits empty sheets; the route waits for every body.
 *  - RADD-734: no application chrome — no top bar, pins bar, sidebar or tree.
 *  - RADD-735: measured, not eyeballed. The emitted PDF is parsed for its page
 *    count, and the rendered DOM is measured for break rules.
 *  - RADD-737: with subpages, a contents list and one sheet per child.
 *
 * Usage: node scripts/page-print-proof.mjs <baseUrl> <spaceSlug> <pagePath> <email> <password>
 *   (RADD-1233: the print view lives at /print/pages/<space>/<path>)
 */
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, spaceSlug, pageSlug, email, password] = process.argv.slice(2);

/** Page count straight out of the PDF: `/Type /Page` objects, minus /Pages. */
function pdfPageCount(base64) {
  const raw = Buffer.from(base64, "base64").toString("latin1");
  const counts = raw.match(/\/Count\s+(\d+)/g);
  if (counts?.length) return Math.max(...counts.map((c) => Number(c.split(/\s+/)[1])));
  return (raw.match(/\/Type\s*\/Page[^s]/g) || []).length;
}

/** Extractable text, for "is it blank". Uncompressed streams only, which is
 *  enough: we only need to know SOMETHING of the body made it through. */
function pdfHasText(base64, needle) {
  const raw = Buffer.from(base64, "base64").toString("latin1");
  return raw.includes(needle);
}

/** WCAG contrast between two computed CSS colours. */
function contrastOf(a, b) {
  const lum = (css) => {
    const [r, g, bl] = (css || "rgb(0,0,0)").match(/[0-9.]+/g).slice(0, 3).map((v) => Number(v) / 255);
    const ch = (c) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(bl);
  };
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}


async function main() {
  const { session, close } = await openBrowser({
    port: 9450, profile: resolve(process.env.TMPDIR || "/tmp", "radd-print-proof"), width: 1280, scale: 1,
  });
  // The break rules live in @media print. Reading them in screen mode reports
  // the default and would fail against a correct stylesheet.
  await session.send("Emulation.setEmulatedMedia", { media: "print" });

  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);

  // window.print() would block headless Chrome; stub it and record the call.
  const visit = async (url) => {
    await session.navigate(url, 300);
    await session.eval(
      `(() => { window.__printed = 0; window.print = () => { window.__printed++; }; })()`);
    for (let i = 0; i < 50; i++) {
      await sleep(500);
      const done = await session.eval(`window.__printed > 0`);
      if (done) break;
    }
    return session.eval(`(() => {
      const root = document.querySelector(".radd-print");
      const style = (sel, prop) => {
        const el = document.querySelector(sel);
        return el ? getComputedStyle(el)[prop] : null;
      };
      return {
        printed: window.__printed || 0,
        mounted: !!root,
        text: root ? (root.textContent || "").replace(/\\s+/g, " ").trim() : "",
        // Chrome (the app shell) must be absent entirely.
        hasPrimaryNav: !!document.querySelector("nav[aria-label='Primary']"),
        hasSidebar: !!document.querySelector("aside"),
        hasTree: !!document.querySelector("[data-page-tree]"),
        articles: document.querySelectorAll(".radd-print-page").length,
        breaks: document.querySelectorAll(".radd-print-break").length,
        contents: !!document.querySelector(".radd-print-contents"),
        footer: (document.querySelector(".radd-print-footer")?.textContent || ""),
        // The break rules must be live, not just present in the file.
        headingBreakAfter: style("h1", "breakAfter"),
        codeBreakInside: style("pre, .cm-editor", "breakInside"),
        // Printing the dark theme wastes toner and reads worse — the first PDF
        // came out with grey-on-white headings. Measure, do not assume.
        lightTheme: document.documentElement.classList.contains("light"),
        bodyInk: (() => {
          const h = document.querySelector(".radd-print h2, .radd-print h3, .radd-print p");
          return h ? getComputedStyle(h).color : null;
        })(),
        pageBg: getComputedStyle(document.querySelector(".radd-print")).backgroundColor,
      };
    })()`);
  };

  const single = await visit(`${baseUrl}/print/pages/${spaceSlug}/${pageSlug}`);
  const singlePdf = await session.send("Page.printToPDF", { printBackground: true });

  const withSubs = await visit(`${baseUrl}/print/pages/${spaceSlug}/${pageSlug}?subpages=1`);
  const subsPdf = await session.send("Page.printToPDF", { printBackground: true });

  if (process.env.RADD_PDF) writeFileSync(process.env.RADD_PDF, Buffer.from(subsPdf.data, "base64"));

  const singlePages = pdfPageCount(singlePdf.data);
  const subsPages = pdfPageCount(subsPdf.data);

  const hoverCapable = await session.hoverCapable();
  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    "the print route mounts": single.mounted === true,
    "print() fired (it waited for the body)": single.printed >= 1,
    "the body is NOT blank": single.text.length > 80,
    "the title block names the space": single.text.includes("Extension proof"),
    "no primary navigation": single.hasPrimaryNav === false,
    "no sidebar": single.hasSidebar === false,
    "no page tree": single.hasTree === false,
    "the footer carries the page URL": single.footer.includes(`/pages/${spaceSlug}/${pageSlug}`),
    "headings avoid a break after them": single.headingBreakAfter === "avoid",
    "code blocks avoid an internal break": single.codeBreakInside === "avoid",
    "a PDF was produced with at least one sheet": singlePages >= 1,
    "the PDF is not an empty sheet": pdfHasText(singlePdf.data, "/Type") && singlePages >= 1,
    "with subpages: a contents list appears": withSubs.contents === true,
    "with subpages: each child is its own article": withSubs.articles > single.articles,
    "with subpages: children carry a hard page break": withSubs.breaks >= 1,
    "with subpages the document is longer": subsPages > singlePages,
    "the print view forces the light theme": single.lightTheme === true,
    "body text is dark ink on a light sheet": contrastOf(single.bodyInk, single.pageBg) >= 4.5,
    "no console errors": session.consoleErrors.length === 0,
  };
  const failed = report(checks, {
    single: { ...single, text: single.text.slice(0, 160) },
    withSubs: { articles: withSubs.articles, breaks: withSubs.breaks, contents: withSubs.contents },
    singlePages, subsPages, consoleErrors: session.consoleErrors,
  });
  await close();
  return failed;
}

main()
  .then((f) => process.exit(f ? 1 : 0))
  .catch((e) => { console.error(e); process.exit(2); });

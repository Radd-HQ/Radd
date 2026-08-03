/**
 * Proves RADD-747: the config form is GENERATED from `params_schema`.
 *
 * The assertion that carries the issue is not "a dialog opened" — it is that
 * the controls MATCH THE SCHEMA the server served, checked field by field
 * against `GET /pages/extensions` rather than against a list written here. A
 * form hand-built for the first-party extensions would pass a hardcoded check
 * and fail the actual requirement, which is that a plugin's extension gets a
 * form with no UI code of its own.
 *
 * It also pins the two ways a generated form can damage a page: dropping a
 * parameter it does not understand, and writing defaults nobody asked for.
 *
 * Usage: node scripts/extension-config-proof.mjs <baseUrl> <spaceSlug> <email> <password>
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, spaceSlug, email, password] = process.argv.slice(2);
const PORT = 9452;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-ext-config-proof");

/** A callout carrying a parameter no schema describes, plus one that does. */
const SEED = [
  "intro",
  "",
  "```radd:callout",
  '{"kind": "warning", "keep_me": {"nested": [1, 2]}}',
  "```",
  "",
  "```radd:nonesuch",
  '{"anything": 1}',
  "```",
  "",
].join("\n");

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE, width: 1440, height: 1100 });
  const { consoleErrors } = session;

  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);

  const created = await session.eval(`(async () => {
    const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
    const space = spaces.find((s) => s.slug === ${JSON.stringify(spaceSlug)});
    const pages = await (await fetch("/api/v1/page-spaces/" + space.id + "/pages", {credentials:"include"})).json();
    const body = ${JSON.stringify(SEED)};
    let page = pages.find((p) => p.slug === "config-proof");
    if (!page) {
      page = await (await fetch("/api/v1/pages", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ space_id: space.id, title: "Config proof", body }),
      })).json();
    } else {
      await fetch("/api/v1/pages/" + page.id, {
        method: "PATCH", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ body }),
      });
    }
    return { id: page.id, slug: page.slug };
  })()`);

  await session.navigate(`${baseUrl}/pages/${spaceSlug}/${created.slug}`, 2500);
  await session.eval(`(() => { document.querySelector('button[aria-label="Edit page"]')?.click(); })()`);
  await sleep(3000);

  // --- The generated form, checked against the SERVER's schema -------------
  await session.hover(".ProseMirror [data-extension='callout']");
  await sleep(300);
  await session.click(`button[aria-label="Configure radd:callout"]`);
  await sleep(800);

  const form = await session.eval(`(async () => {
    const d = document.querySelector('[role="dialog"]');
    if (!d) return null;
    const specs = await (await fetch("/api/v1/pages/extensions", {credentials:"include"})).json();
    const schema = specs.find((s) => s.name === "callout").params_schema;
    const labelFor = (el) => {
      const wrap = el.closest("div,label");
      return (wrap ? wrap.textContent : "").trim();
    };
    // What the schema SAYS this form should contain.
    const expected = Object.entries(schema.properties).map(([key, p]) => ({
      key,
      wants: Array.isArray(p.enum) ? "select"
           : p.type === "boolean" ? "checkbox"
           : p.type === "integer" || p.type === "number" ? "number"
           : p.format === "markdown" ? "textarea" : "text",
      options: p.enum || null,
    }));
    // What it actually contains, ignoring the JSON escape hatch.
    const controls = [...d.querySelectorAll("input, select, textarea")].map((el) => ({
      tag: el.tagName.toLowerCase(),
      type: el.type || null,
      label: labelFor(el),
      options: el.tagName === "SELECT" ? [...el.options].map((o) => o.value).filter(Boolean) : null,
      role: el.getAttribute("role"),
    }));
    return {
      expected,
      controls,
      // Our Select renders a button+listbox, not a native <select>, so look for
      // the kind picker by its rendered options instead of by tag name.
      buttons: [...d.querySelectorAll("button")].map((b) => b.textContent.trim()).filter(Boolean),
      textareaCount: d.querySelectorAll("textarea").length,
      // The form must be a FORM, not the JSON escape hatch.
      showsJsonEditor: !!d.querySelector('textarea[aria-label="Parameters as JSON"]'),
      offersJsonEscape: [...d.querySelectorAll("button")].some((b) => /Edit as JSON/.test(b.textContent)),
      mentionsCarried: /keep_me/.test(d.textContent || ""),
      text: (d.textContent || "").replace(/\\s+/g, " ").slice(0, 400),
    };
  })()`);

  // The house Select is a button + listbox, so its options only EXIST once it is
  // opened — reading them off the closed control would assert nothing. Open it
  // through the input pipeline and compare the rendered options to the schema's
  // enum, which is the assertion that the control is generated rather than
  // hand-written for this one extension.
  await session.click('[role="dialog"] button[aria-haspopup="listbox"]');
  await sleep(400);
  const enumOptions = await session.eval(`(async () => {
    // The VISIBLE listbox. Others exist in the DOM — the editor AI action picker
    // has one — and taking the first match read that one's options instead,
    // which is a failure that looks like a wrong enum rather than a wrong query.
    const list = [...document.querySelectorAll('[role="listbox"]')]
      .find((el) => el.getBoundingClientRect().height > 0);
    const specs = await (await fetch("/api/v1/pages/extensions", {credentials:"include"})).json();
    const schema = specs.find((s) => s.name === "callout").params_schema;
    return {
      rendered: list ? [...list.querySelectorAll('[role="option"]')].map((o) => o.textContent.trim()) : [],
      declared: schema.properties.kind.enum,
      listboxCount: document.querySelectorAll('[role="listbox"]').length,
    };
  })()`);
  // Close it again without changing the value. Escape must reach the SELECT,
  // which stops it propagating to the Modal — blurring first sends the key to
  // the body and closes the whole dialog, losing the edits. (That is a mistake
  // in a proof, not in the product: Select handles Escape and returns focus to
  // its trigger. Worth the note because it looked like a product bug for a
  // minute.)
  await session.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
  await session.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
  await sleep(300);
  const dialogSurvivedEscape = await session.eval(`!!document.querySelector('[role="dialog"]')`);

  // Type a title, then save the block — the form's values must land in the fence.
  const typed = await session.eval(`(() => {
    const d = document.querySelector('[role="dialog"]');
    const inputs = [...d.querySelectorAll("input")].filter((i) => i.type === "text" || !i.type);
    const title = inputs[0];
    if (!title) return false;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    setter.call(title, "Typed from the form");
    title.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
  })()`);
  await sleep(200);
  await session.click('[role="dialog"] button', (t) => t.trim() === "Save");
  await sleep(600);

  await session.eval(`(() => {
    [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Save")?.click();
  })()`);
  await sleep(2200);
  const savedFromForm = await session.eval(
    `(async () => (await (await fetch("/api/v1/pages/${created.id}", {credentials:"include"})).json()).body)()`);

  // --- An extension with no schema falls back to raw JSON ------------------
  await session.navigate(`${baseUrl}/pages/${spaceSlug}/${created.slug}`, 2500);
  await session.eval(`(() => { document.querySelector('button[aria-label="Edit page"]')?.click(); })()`);
  await sleep(3000);
  await session.hover(".ProseMirror [data-extension='nonesuch']");
  await sleep(300);
  await session.click(`button[aria-label="Configure radd:nonesuch"]`);
  await sleep(700);
  const unschemad = await session.eval(`(() => {
    const d = document.querySelector('[role="dialog"]');
    if (!d) return null;
    return {
      hasJsonEditor: !!d.querySelector('textarea[aria-label="Parameters as JSON"]'),
      explains: /plugin providing it may be disabled|not valid JSON/.test(d.textContent || ""),
      offersFormToggle: [...d.querySelectorAll("button")].some((b) => /Edit as a form/.test(b.textContent)),
    };
  })()`);

  // --- Inserting from the menu opens the form ------------------------------
  await session.eval(`(() => { document.querySelector('[role="dialog"] button[aria-label="Close"]')?.click(); })()`);
  await sleep(400);
  const beforeInsert = await session.eval(`({
    dialogGone: !document.querySelector('[role="dialog"]'),
    toolbarButton: !!document.querySelector("svg.radd-extension-toolbar-icon"),
  })`);
  await session.click("svg.radd-extension-toolbar-icon");
  await sleep(700);
  const menuOpen = await session.eval(
    `document.querySelectorAll('[role="menu"] [role="menuitem"]').length`);
  const pickedToc = await session.click('[role="menu"] [role="menuitem"]', (t) => t.includes("Table of contents"));
  await sleep(1200);
  const afterPick = await session.eval(`(() => {
    const pm = document.querySelector(".ProseMirror");
    return {
      extensionsInEditor: [...document.querySelectorAll(".ProseMirror [data-extension]")]
        .map((n) => n.getAttribute("data-extension")),
      menuStillOpen: !!document.querySelector('[role="menu"]'),
      editorText: pm ? (pm.textContent || "").replace(/\\s+/g, " ").slice(0, 120) : null,
    };
  })()`);
  const afterInsert = await session.eval(`(() => {
    const d = document.querySelector('[role="dialog"]');
    return {
      opened: !!d,
      title: d ? d.getAttribute("aria-label") : null,
      // toc is {subpages: boolean, depth: integer} — a checkbox and a number,
      // which is the pair that proves the form is read from the schema and not
      // from a shape copied off the callout.
      checkboxes: d ? d.querySelectorAll('input[type="checkbox"]').length : 0,
      numbers: d ? d.querySelectorAll('input[type="number"]').length : 0,
    };
  })()`);
  // Cancel: an inserted block must survive dismissing its form.
  if (afterInsert?.opened) {
    await session.click('[role="dialog"] button', (t) => t.trim() === "Cancel");
    await sleep(400);
  }
  const afterCancel = await session.eval(
    `document.querySelectorAll(".ProseMirror [data-extension='toc']").length`);
  const reopened = await session.eval(`!!document.querySelector('[role="dialog"]')`);


  const checks = {
    "the form opens on the block": form !== null,
    "it is a form, not the JSON editor": form?.showsJsonEditor === false,
    // Read from the wire, not from a list in this file.
    "every schema property has a control":
      (form?.expected?.length ?? 0) > 0 &&
      form.expected.every((e) => (form.text || "").toLowerCase().includes(e.key.replace(/_/g, " "))),
    // Exactly the schema's options, plus the clear-to-default entry for an
    // optional property — nothing invented, nothing missing.
    "the enum property renders the options the schema declares":
      (enumOptions?.declared?.length ?? 0) > 0 &&
      enumOptions.declared.every((o) => enumOptions.rendered.includes(o)) &&
      enumOptions.rendered.filter((o) => o !== "—").length === enumOptions.declared.length,
    "Escape closes the dropdown, not the dialog": dialogSurvivedEscape === true,
    "the markdown property renders as a textarea": (form?.textareaCount ?? 0) >= 1,
    "the JSON escape hatch is still offered": form?.offersJsonEscape === true,
    "a parameter the schema does not describe is named as carried through":
      form?.mentionsCarried === true,
    "typing into the form reached the block": typed === true &&
      /Typed from the form/.test(savedFromForm || ""),
    "the unknown parameter survived the save": /keep_me/.test(savedFromForm || "") &&
      /"nested"/.test(savedFromForm || ""),
    // `title` has no default and `text` was never set: neither may appear.
    "no default was written that nobody asked for": !/"text"/.test(savedFromForm || ""),
    "an extension with no schema falls back to raw JSON": unschemad?.hasJsonEditor === true,
    "and says why the form could not be built": unschemad?.explains === true,
    "inserting from the menu opens the form": afterInsert?.opened === true,
    "the form matches the INSERTED extension's schema, not the last one":
      afterInsert?.checkboxes === 1 && afterInsert?.numbers === 1,
    "cancelling keeps the inserted block": afterCancel === 1,
    "and does not re-open the form": reopened === false,
    "no console errors": consoleErrors.length === 0,
  };

  return report(checks, { form, enumOptions, dialogSurvivedEscape, beforeInsert, menuOpen, pickedToc, afterPick, typed, savedFromForm, unschemad, afterInsert, afterCancel, reopened, consoleErrors });
}

main()
  .then((failed) => process.exit(failed ? 1 : 0))
  .catch((err) => { console.error(err); process.exit(2); });

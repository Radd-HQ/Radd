/**
 * Convert Jira pages markup to Markdown — the frontend twin of the importer's
 * `scripts/jira_markup.py`. KEEP THE TWO IN LOCKSTEP: same rules, same order.
 * Makes the editor + viewer backwards-compatible with Jira: imported (or pasted)
 * Jira content renders and edits correctly, while native Markdown passes through
 * untouched (gated on constructs that never occur in normal Markdown).
 *
 * Handles: `[text|url]` / `[url]` links, `[~user]` mentions, `{quote}` / `{panel}`,
 * `{code}` / `{noformat}` blocks, `{{mono}}`, `hN.` headings, `||header||` / `|cell|`
 * tables, `#` / nested `*#` lists, `*bold*`, `-struck-`, `{color}` (stripped),
 * `{anchor}` / `{toc}` (stripped), `!image.png!` embeds, and Jira emoticons.
 */

// Code + noformat in ONE alternation so whichever block opens first consumes any
// markers nested inside it (correct Jira semantics + no interleaved placeholders).
const FENCED_RE =
  /\{code(?::(?<lang>[^}]*))?\}(?<cbody>[\s\S]*?)\{code\}|\{noformat(?::[^}]*)?\}(?<nbody>[\s\S]*?)\{noformat\}/g;
const PANEL_RE = /\{panel(?::([^}]*))?\}(?<pbody>[\s\S]*?)\{panel\}/g;
const QUOTE_RE = /\{quote\}([\s\S]*?)\{quote\}/g;
const COLOR_RE = /\{color(?::[^}]*)?\}/g;
const ANCHOR_RE = /\{anchor:[^}]*\}/g;
const TOC_RE = /^\{toc[^}]*\}[ \t]*\n?/gm;
const MONO_RE = /\{\{(.+?)\}\}/g;
const LINK_RE = /\[([^\]|\n]+)\|([^\]|\n]+?)(?:\|[^\]\n]*)?\]/g;
const BARE_URL_RE = /\[((?:https?|mailto):[^\]\s|]+)\]/g;
const USER_RE = /\[~([\w.\-]+)\]/g;
const HEADING_RE = /^h([1-6])\.\s+/gm;
// `*bold*` → `**bold**`. Not adjacent to word chars / another `*`, and the content
// can't start/end with `*` or whitespace — so native `**strong**` (incl. our own
// panel-title output), mid-word stars and `* list` markers never match.
const BOLD_RE = /(?<![\w*\\])\*([^\s*](?:[^*\n]*?[^\s*])?)\*(?![\w*])/g;
// `-struck-` → `~~struck~~`. Whitespace-delimited, not digit-led, and the content
// can't start/end with `-` — so ranges ("-5-10"), `--flags`, `---` rules and table
// separator rows pass through.
const STRIKE_RE = /(?:^|(?<=\s))-(?!\d)([^\s-](?:[^-\n]*?[^\s-])?)-(?=$|[\s.,;:!?])/gm;
// `!image.png!` / `!http://…!` embeds — only when the body looks like a file/URL.
const IMAGE_RE = /!([^!\s|]+)(?:\|[^!\n]*)?!/g;
const IMAGE_EXT_RE = /\.(png|jpe?g|gif|webp|svg|bmp)$/i;
const URL_RE = /^https?:\/\//i;
// Jira renders these as icons/emoji, so converting is faithful to what Jira showed.
const EMOTICONS: readonly (readonly [string, string])[] = [
  ["(/)", "✅"],
  ["(x)", "❌"],
  ["(!)", "⚠️"],
  ["(?)", "❓"],
  ["(i)", "ℹ️"],
  ["(+)", "➕"],
  ["(-)", "➖"],
  ["(y)", "👍"],
  ["(n)", "👎"],
  [":D", "😄"],
  [":P", "😛"],
  [";)", "😉"],
  [":)", "🙂"],
  [":(", "🙁"],
];
const EMOTICON_MAP = new Map(EMOTICONS);
const EMOTICON_RE = new RegExp(
  "(?:^|(?<=\\s))(?:" +
    EMOTICONS.map(([token]) => token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") +
    ")(?=$|[\\s.,;:!?])",
  "gm",
);

// A quick gate: only touch text that actually looks like Jira markup. The ambiguous
// rules (bold, `#` lists, strike, emoticons) are safe to run *because* of this gate —
// a gated text is Jira-origin, where `# x` is a list item, never a Markdown heading.
const HAS_JIRA_RE =
  /\{code|\{noformat[:}]|\{quote\}|\{panel[:}]|\{color[:}]|\{anchor:|^\{toc|\{\{|\[[^\]\n]*\||\[(?:https?|mailto):|\[~|^h[1-6]\.|^\s*\|\|[^|]|!\S+\.(?:png|jpe?g|gif|webp|svg|bmp)(?:\|[^!\n]*)?!/m;

// Sentinel that protects stashed code blocks from the inline rules — a control char
// that never appears in real prose. (fromCharCode keeps the source free of raw controls.)
const SENT = String.fromCharCode(1);
const NUL = String.fromCharCode(0);

/** `{code:java}` and `{code:title=x|language=java}` both carry a language. */
function cleanLang(params: string): string {
  const trimmed = params.trim();
  if (!trimmed.includes("=")) return /^[\w+-]*$/.test(trimmed) ? trimmed : "";
  return /(?:^|\|)language=([\w+-]+)/.exec(trimmed)?.[1] ?? "";
}

function panelToQuote(params: string | undefined, body: string): string {
  const title = /(?:^|\|)title=([^|}]*)/.exec(params ?? "")?.[1]?.trim();
  const lines = body.trim().split("\n").map((line) => "> " + line);
  if (title) lines.unshift("> **" + title + "**", ">");
  return "\n" + lines.join("\n") + "\n";
}

/** `||h1||h2||` / `|c1|c2|` — normalize a line's cells (`||` is Jira's header marker). */
function splitCells(line: string): string[] {
  const inner = line.trim().replace(/\|\|/g, "|").replace(/^\|/, "").replace(/\|$/, "");
  return inner.split("|").map((cell) => cell.trim());
}

/** Line-based pass: Jira tables → GFM tables, Jira `#`/nested lists → Markdown lists.
 * Runs BEFORE the `hN.` heading rule so it never sees converted `# ` headings. */
function convertLines(text: string): string {
  const lines = text.split("\n");
  const out: string[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^\s*\|/.test(line)) {
      const rows: string[][] = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(splitCells(lines[i++]));
      const width = Math.max(...rows.map((row) => row.length));
      // GFM needs a header + separator; a blank line keeps it out of a paragraph.
      if (out.length && out[out.length - 1].trim() !== "") out.push("");
      out.push("| " + rows[0].join(" | ") + " |");
      out.push("|" + Array.from({ length: width }, () => " --- |").join(""));
      for (const row of rows.slice(1)) out.push("| " + row.join(" | ") + " |");
      continue;
    }
    // `# x` ordered, `* x`/`- x` bullets, `**`/`##`/mixed runs = nesting (last char
    // decides the type). Single `*`/`-` is already valid Markdown — leave it alone.
    const list = /^([*#-]{1,6})[ \t]+(.*)$/.exec(line);
    if (list && !(list[1].length === 1 && list[1] !== "#")) {
      const marker = list[1].endsWith("#") ? "1." : "-";
      out.push("    ".repeat(list[1].length - 1) + marker + " " + list[2]);
      i++;
      continue;
    }
    out.push(line);
    i++;
  }
  return out.join("\n");
}

export function jiraToMarkdown(text: string): string {
  if (!text || !HAS_JIRA_RE.test(text)) return text ?? "";

  const blocks: string[] = [];
  let out = text.replace(
    FENCED_RE,
    (_m, lang: string | undefined, cbody: string | undefined, nbody: string | undefined) => {
      const fenced =
        cbody !== undefined
          ? "```" + cleanLang(lang ?? "") + "\n" + cbody.replace(/^\n+|\n+$/g, "") + "\n```"
          : "```\n" + (nbody ?? "").replace(/^\n+|\n+$/g, "") + "\n```";
      blocks.push(fenced);
      return `${SENT}${blocks.length - 1}${SENT}`;
    },
  );

  out = out.replace(ANCHOR_RE, "").replace(TOC_RE, "");
  out = out.replace(PANEL_RE, (_m, params: string | undefined, body: string) =>
    panelToQuote(params, body),
  );
  out = out.replace(
    QUOTE_RE,
    (_m, inner: string) =>
      "\n" + inner.trim().split("\n").map((line) => "> " + line).join("\n") + "\n",
  );
  out = out.replace(COLOR_RE, "");
  out = out.replace(MONO_RE, "`$1`");
  out = out.replace(LINK_RE, "[$1]($2)"); // before tables: removes `|` from links
  out = out.replace(BARE_URL_RE, "<$1>");
  out = out.replace(USER_RE, "@$1");
  out = convertLines(out);
  out = out.replace(HEADING_RE, (_m, level: string) => "#".repeat(Number(level)) + " ");
  out = out.replace(BOLD_RE, "**$1**");
  out = out.replace(STRIKE_RE, "~~$1~~");
  out = out.replace(EMOTICON_RE, (token) => EMOTICON_MAP.get(token) ?? token);
  out = out.replace(IMAGE_RE, (match, src: string) => {
    if (URL_RE.test(src)) return `![](${src})`;
    if (IMAGE_EXT_RE.test(src)) return `*(image: ${src})*`; // attachment never imported
    return match;
  });

  // Reverse order so a placeholder nested inside another block still resolves.
  for (let i = blocks.length - 1; i >= 0; i--) {
    out = out.split(`${SENT}${i}${SENT}`).join("\n" + blocks[i] + "\n");
  }
  // Hard guard: never surface a NUL or a stray sentinel.
  return out.split(NUL).join("").split(SENT).join("");
}

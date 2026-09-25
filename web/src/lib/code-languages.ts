import { LanguageDescription } from "@codemirror/language";
import { languages } from "@codemirror/language-data";

/**
 * Languages CodeMirror can load, keyed by the token a FENCE should carry.
 *
 * Not `alias[0]`, which is what this did first and got wrong in a way that only
 * shows up outside Radd: JavaScript's alias list begins `ecmascript`, so picking
 * "JavaScript" wrote ```` ```ecmascript ````. Valid, resolvable here, and a
 * fence nobody writes — GitHub and every other renderer of this markdown would
 * fail to highlight it. The lowercased NAME is what people type, so it wins
 * whenever it is a single token; a multi-word name ("Web IDL") falls back to the
 * first whitespace-free alias, since a fence's info string ends at the space.
 */
export function languageOptions(): { value: string; label: string }[] {
  const seen = new Set<string>();
  const out: { value: string; label: string }[] = [];
  for (const description of languages) {
    const value = fenceTokenFor(description);
    if (!value || seen.has(value)) continue;
    seen.add(value);
    out.push({ value, label: description.name });
  }
  return out.sort((a, b) => a.label.localeCompare(b.label));
}

function fenceTokenFor(description: LanguageDescription): string {
  const name = description.name.toLowerCase();
  if (!/\s/.test(name)) return name;
  return description.alias.find((alias) => !/\s/.test(alias)) ?? "";
}

/**
 * Resolve a language name, alias or filename extension, if any.
 *
 * Two lookups, because people write fences with FILE EXTENSIONS and
 * `matchLanguageName` only knows names and aliases. ```` ```py ```` is the
 * obvious case: `py` is listed under Python's `extensions`, not its `alias`, so
 * the name lookup returned null and the block rendered with no highlighting at
 * all — while ```` ```python ```` worked, which makes it look like highlighting
 * is broken at random. Confluence writes `py` too, so every imported Python
 * block arrived unhighlighted.
 *
 * `matchFilename` is CodeMirror's own answer to that: give it a filename and it
 * consults the extension lists. A bare token becomes `x.<token>`.
 */
export const describeLanguage = (name: string): LanguageDescription | null => {
  const token = name.trim().toLowerCase();
  if (!token) return null;
  return (
    LanguageDescription.matchLanguageName(languages, token, true) ??
    LanguageDescription.matchFilename(languages, `x.${token}`)
  );
};


import { LanguageDescription } from "@codemirror/language";
import { languages } from "@codemirror/language-data";

/**
 * Languages CodeMirror can load, keyed by the token a FENCE should carry: the lowercased NAME, not
 * `alias[0]` (JavaScript's is `ecmascript`, which no other renderer highlights). A multi-word name
 * falls back to the first whitespace-free alias — a fence's info string ends at the space.
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
 * Resolve a language name, alias or filename extension, if any. Two lookups: `matchLanguageName`
 * knows names and aliases only, and fences are often EXTENSIONS (```` ```py ````, which Confluence
 * writes too); `matchFilename` resolves those, given `x.<token>`.
 */
export const describeLanguage = (name: string): LanguageDescription | null => {
  const token = name.trim().toLowerCase();
  if (!token) return null;
  return (
    LanguageDescription.matchLanguageName(languages, token, true) ??
    LanguageDescription.matchFilename(languages, `x.${token}`)
  );
};


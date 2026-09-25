import { HighlightStyle } from "@codemirror/language";
import { tags } from "@lezer/highlight";

/** Theme-following highlight. The app's palette, not one-dark's opinion. */
export const codeHighlight = HighlightStyle.define([
  { tag: [tags.keyword, tags.modifier, tags.controlKeyword], color: "var(--code-keyword)" },
  { tag: [tags.string, tags.special(tags.string)], color: "var(--code-string)" },
  { tag: [tags.comment, tags.lineComment, tags.blockComment], color: "var(--code-comment)", fontStyle: "italic" },
  { tag: [tags.number, tags.bool, tags.null], color: "var(--code-number)" },
  { tag: [tags.function(tags.variableName), tags.function(tags.propertyName)], color: "var(--code-function)" },
  { tag: [tags.typeName, tags.className, tags.namespace], color: "var(--code-type)" },
  { tag: [tags.propertyName, tags.attributeName], color: "var(--code-property)" },
  { tag: [tags.operator, tags.punctuation, tags.bracket], color: "var(--code-punct)" },
  { tag: [tags.invalid], color: "var(--code-invalid)" },
]);


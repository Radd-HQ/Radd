/**
 * What to CALL the modifier key (RADD-906).
 *
 * Every shortcut handler in the SPA already accepts both — `event.metaKey ||
 * event.ctrlKey` — so the shortcuts have always worked everywhere. Only the
 * LABELS were wrong: ten places rendered a literal `⌘`, so a Windows or Linux
 * user was told to press a key their keyboard does not have, for a shortcut that
 * would have worked if they had guessed Ctrl. Reported from studio dogfooding, where the
 * artists are on Linux and the leads are on Macs.
 *
 * Resolved ONCE at module load. The platform cannot change mid-session, and a
 * hook would make every label a re-render's worth of work for an answer that is
 * already known.
 */

/** Apple platforms use ⌘; everything else uses Ctrl. */
function detectApple(): boolean {
  if (typeof navigator === "undefined") return false;
  // `userAgentData.platform` is the non-deprecated answer where it exists.
  const modern = (navigator as { userAgentData?: { platform?: string } }).userAgentData;
  if (modern?.platform) return /mac/i.test(modern.platform);
  // `navigator.platform` is deprecated but still the most reliable fallback —
  // and it reports "MacIntel" on Apple Silicon too. iPadOS reports "MacIntel"
  // as well, which is correct here: an iPad keyboard has ⌘.
  if (navigator.platform) return /mac|iphone|ipad|ipod/i.test(navigator.platform);
  return /mac os x/i.test(navigator.userAgent ?? "");
}

export const IS_APPLE = detectApple();

/** The modifier's NAME: `⌘` or `Ctrl`. */
export const MOD_KEY = IS_APPLE ? "⌘" : "Ctrl";

/** The shift modifier's name: `⇧` or `Shift`. */
export const SHIFT_KEY = IS_APPLE ? "⇧" : "Shift";

/**
 * A rendered shortcut: `⌘K` on a Mac, `Ctrl+K` elsewhere.
 *
 * The separator differs because the conventions differ — macOS composes glyphs
 * with no separator, Windows and Linux join names with `+`. Rendering `⌘+K` or
 * `CtrlK` would be wrong on both.
 */
export function shortcut(...parts: string[]): string {
  return parts.join(IS_APPLE ? "" : "+");
}

/** `⌘K` / `Ctrl+K` — the common case. */
export function modShortcut(key: string): string {
  return shortcut(MOD_KEY, key);
}

/** `⇧⌘Z` / `Shift+Ctrl+Z`. */
export function shiftModShortcut(key: string): string {
  return shortcut(SHIFT_KEY, MOD_KEY, key);
}

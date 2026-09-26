/**
 * Copy text on plain-`http://` installs too: `navigator.clipboard` exists only in a secure context,
 * so fall back to `execCommand("copy")` and report whether anything was copied — a caller shows
 * "Copied" because text was copied, not because a click happened.
 */
export async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Denied by permission policy, or a non-secure context that exposes the
      // API but refuses it. Fall through rather than giving up.
    }
  }
  return legacyCopy(text);
}

/** The pre-Clipboard-API path: a selected off-screen textarea plus execCommand.
 * Deprecated, and the only thing that works without a secure context. */
function legacyCopy(text: string): boolean {
  const area = document.createElement("textarea");
  area.value = text;
  // Off-screen rather than hidden: `display:none` and `visibility:hidden` are
  // not selectable, so the copy would be of an empty selection.
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.top = "-1000px";
  area.style.opacity = "0";
  document.body.appendChild(area);
  try {
    area.select();
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    area.remove();
  }
}

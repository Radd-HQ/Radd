/**
 * Copying text, on the instances Radd actually runs on.
 *
 * `navigator.clipboard` exists only in a SECURE CONTEXT. Radd is self-hosted and
 * a good number of installs sit on plain `http://` inside a network, where the
 * API is `undefined` — so `navigator.clipboard.writeText(x)` throws, and the
 * common `void navigator.clipboard?.writeText(x)` form swallows the call and
 * leaves an unhandled rejection in the console. Either way the button does
 * nothing and says nothing, which is the worst of the three outcomes.
 *
 * So: try the real API, fall back to the old `execCommand("copy")` trick, and
 * return whether anything actually happened. A caller that shows "Copied" should
 * show it because text was copied, not because a click was received.
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

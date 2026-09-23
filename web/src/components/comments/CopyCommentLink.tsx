import { useState } from "react";
import { Check, Link2 } from "lucide-react";

/**
 * RADD-1297: copy a link that lands on ONE comment. Offered to every reader —
 * a link is only as useful as the people it can be sent to, and the landing
 * itself enforces who may see the comment (404 = the page opens as usual).
 * Quiet until the row is hovered or the button is focused, like the other
 * per-comment actions.
 */
export function CopyCommentLink({ href, className = "" }: { href: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(href);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // No clipboard (an insecure origin): the address bar route still works.
      window.prompt("Copy this link", href);
    }
  };
  return (
    <button
      type="button"
      onClick={() => void copy()}
      aria-label={copied ? "Link copied" : "Copy link to this comment"}
      title={copied ? "Link copied" : "Copy link to this comment"}
      data-copy-comment-link
      className={
        "rounded p-0.5 text-fg-faint hover:bg-elevated hover:text-fg focus-visible:opacity-100 cursor-pointer " +
        className
      }
    >
      {copied ? <Check size={11} aria-hidden /> : <Link2 size={11} aria-hidden />}
    </button>
  );
}

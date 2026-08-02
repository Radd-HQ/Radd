import { useState } from "react";
import { Bookmark, CornerDownLeft, Sparkles } from "lucide-react";
import { AiEditorActionKind, type AiEditorAction } from "../../lib/types";
import { actionRun, type AiRun } from "./ai";

/** How much of a freeform prompt the streaming indicator shows as its label. */
const FREEFORM_LABEL_MAX = 40;

interface AiActionPickerProps {
  /** The server-curated menu (builtins + admin presets). */
  actions: AiEditorAction[];
  onPick: (run: AiRun) => void;
  autoFocus?: boolean;
  placeholder?: string;
}

/**
 * "Pick an AI action or type a prompt" — the shared inner panel of the editor
 * toolbar's AI button and the read-mode AI menu (both scopes where Crepe's
 * selection tooltip can't reach: it needs a text selection to anchor to).
 */
export function AiActionPicker({ actions, onPick, autoFocus, placeholder }: AiActionPickerProps) {
  const [prompt, setPrompt] = useState("");

  const submitPrompt = () => {
    const text = prompt.trim();
    if (!text) return;
    onPick({
      instruction: text,
      label: text.length > FREEFORM_LABEL_MAX ? text.slice(0, FREEFORM_LABEL_MAX) + "…" : text,
    });
  };

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-1 rounded-md border border-strong bg-base px-2 py-1 focus-within:outline-2 focus-within:outline-focus">
        <Sparkles size={12} aria-hidden className="shrink-0 text-fg-muted" />
        <input
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              submitPrompt();
            }
          }}
          autoFocus={autoFocus}
          placeholder={placeholder ?? "Tell AI what to do…"}
          aria-label="AI instruction"
          className="min-w-0 flex-1 bg-transparent text-xs text-fg outline-none placeholder:text-fg-faint"
        />
        {prompt.trim() !== "" && (
          <button
            type="button"
            onClick={submitPrompt}
            aria-label="Send prompt"
            className="shrink-0 rounded p-0.5 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
          >
            <CornerDownLeft size={12} aria-hidden />
          </button>
        )}
      </div>
      <ul className="flex flex-col">
        {actions.map((action) => (
          <li key={action.id}>
            <button
              type="button"
              onClick={() => onPick(actionRun(action))}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs text-fg hover:bg-elevated cursor-pointer"
            >
              {action.kind === AiEditorActionKind.preset ? (
                <Bookmark size={12} aria-hidden className="shrink-0 text-fg-muted" />
              ) : (
                <Sparkles size={12} aria-hidden className="shrink-0 text-fg-muted" />
              )}
              {action.label}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

import { useCallback, useEffect, useRef, useState } from "react";
import { SLQ_SUGGEST_DEBOUNCE_MS } from "./constants";
import { fetchSlqSuggest, suggestContextLabel, type SlqSuggestion } from "./slq-suggest";

/**
 * Server-driven SLQ autocomplete controller (spec 13). Owns the debounced,
 * stale-dropping suggest fetch and the dropdown's open/active state; the editor
 * component reads the caret and applies the chosen `insert`. `scope` carries
 * an optional project_id; `null` disables autocomplete entirely.
 */
interface SlqAutocomplete {
  open: boolean;
  suggestions: SlqSuggestion[];
  contextLabel: string | null;
  replaceFrom: number;
  activeIndex: number;
  setActiveIndex: (index: number) => void;
  /** Fetch suggestions for the caret; `immediate` skips the debounce (Ctrl+Space). */
  request: (query: string, cursor: number, immediate?: boolean) => void;
  /** Move the highlight over insertable rows only (hints are skipped), wrapping. */
  moveActive: (delta: number) => void;
  /** The highlighted row if it's insertable, else null. */
  activeSuggestion: () => SlqSuggestion | null;
  close: () => void;
}

const firstSelectable = (rows: SlqSuggestion[]): number => {
  const index = rows.findIndex((row) => row.insert !== "");
  return index === -1 ? 0 : index;
};

export function useSlqAutocomplete(
  scope: Record<string, string> | null,
  dialect?: string,
): SlqAutocomplete {
  const [open, setOpen] = useState(false);
  const [suggestions, setSuggestions] = useState<SlqSuggestion[]>([]);
  const [contextLabel, setContextLabel] = useState<string | null>(null);
  const [replaceFrom, setReplaceFrom] = useState(0);
  const [activeIndex, setActiveIndex] = useState(0);
  const seqRef = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);
  const dialectRef = useRef(dialect);
  dialectRef.current = dialect;
  const timerRef = useRef<number | undefined>(undefined);
  // Keep the latest scope in a ref so `request` stays a stable callback.
  const scopeRef = useRef(scope);
  scopeRef.current = scope;

  const cancel = useCallback(() => {
    seqRef.current += 1;
    window.clearTimeout(timerRef.current);
    controllerRef.current?.abort();
    controllerRef.current = null;
  }, []);

  const close = useCallback(() => {
    cancel();
    setOpen(false);
    setSuggestions([]);
  }, [cancel]);

  useEffect(() => cancel, [cancel]);
  const scopeKey = JSON.stringify(scope);
  useEffect(() => { close(); }, [scopeKey, dialect, close]);

  const run = useCallback(async (query: string, cursor: number) => {
    const activeScope = scopeRef.current;
    if (activeScope === null) return;
    const seq = (seqRef.current += 1);
    const controller = new AbortController();
    controllerRef.current = controller;
    const response = await fetchSlqSuggest(activeScope, query, cursor, dialectRef.current, controller.signal);
    if (seq !== seqRef.current) return; // a newer request superseded this one
    if (!response || response.suggestions.length === 0) {
      setOpen(false);
      setSuggestions([]);
      return;
    }
    setSuggestions(response.suggestions);
    setContextLabel(suggestContextLabel(response));
    setReplaceFrom(response.replace_from);
    setActiveIndex(firstSelectable(response.suggestions));
    setOpen(true);
  }, []);

  const request = useCallback(
    (query: string, cursor: number, immediate = false) => {
      cancel();
      if (scopeRef.current === null) return;
      if (immediate) {
        void run(query, cursor);
        return;
      }
      timerRef.current = window.setTimeout(() => void run(query, cursor), SLQ_SUGGEST_DEBOUNCE_MS);
    },
    [run, cancel],
  );

  const moveActive = useCallback(
    (delta: number) => {
      setActiveIndex((current) => {
        if (suggestions.length === 0) return current;
        let index = current;
        for (let step = 0; step < suggestions.length; step += 1) {
          index = (index + delta + suggestions.length) % suggestions.length;
          if (suggestions[index].insert !== "") return index;
        }
        return current;
      });
    },
    [suggestions],
  );

  const activeSuggestion = useCallback(() => {
    const row = suggestions[activeIndex];
    return row && row.insert !== "" ? row : null;
  }, [suggestions, activeIndex]);

  return {
    open: open && suggestions.length > 0,
    suggestions,
    contextLabel,
    replaceFrom,
    activeIndex,
    setActiveIndex,
    request,
    moveActive,
    activeSuggestion,
    close,
  };
}

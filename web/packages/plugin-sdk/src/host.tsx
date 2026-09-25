import { useSyncExternalStore, type ComponentType } from "react";
import { TextArea } from "./primitives";

/**
 * Host-provided components (RADD-1325).
 *
 * Some controls are too heavy to reimplement in the SDK and too host-specific to bundle into every
 * remote — a CodeMirror editor, the house token-list input, the form generated from a JSON Schema.
 * The HOST provides its own at startup (`provideHostComponents`), and a remote renders them through
 * the wrappers below, which fall back to a plain control when a host provides none. So a plugin's
 * automation-node inspector looks and behaves like the host's own forms without shipping CodeMirror.
 */

export interface CodeEditorProps {
  value: string;
  onChange: (value: string) => void;
  /** e.g. "python". */
  language?: string;
  minHeight?: number;
}

export interface TokenListProps {
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
  ariaLabel?: string;
}

export interface SchemaFormProps {
  schema: Record<string, unknown>;
  params: Record<string, unknown>;
  onChange: (params: Record<string, unknown>) => void;
}

export interface HostComponents {
  CodeEditor?: ComponentType<CodeEditorProps>;
  TokenList?: ComponentType<TokenListProps>;
  SchemaForm?: ComponentType<SchemaFormProps>;
}

let provided: HostComponents = {};
const listeners = new Set<() => void>();

/** Called once by the host at startup. */
export function provideHostComponents(components: HostComponents): void {
  provided = { ...provided, ...components };
  for (const listener of listeners) listener();
}

function useProvided(): HostComponents {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => provided,
  );
}

/** A code editor — the host's CodeMirror, else a monospace text area. */
export function CodeEditor(props: CodeEditorProps) {
  const { CodeEditor: Host } = useProvided();
  if (Host) return <Host {...props} />;
  return (
    <TextArea
      value={props.value}
      onChange={(event) => props.onChange(event.target.value)}
      style={{ fontFamily: "monospace", minHeight: props.minHeight ?? 160 }}
    />
  );
}

/** A list of short strings (answers, port names) — the host's token input, else one per line. */
export function TokenList(props: TokenListProps) {
  const { TokenList: Host } = useProvided();
  if (Host) return <Host {...props} />;
  return (
    <TextArea
      aria-label={props.ariaLabel}
      placeholder={props.placeholder}
      value={props.value.join("\n")}
      onChange={(event) =>
        props.onChange(event.target.value.split("\n").map((line) => line.trim()).filter(Boolean))
      }
    />
  );
}

/** The form generated from a JSON Schema — the same one the host renders for a node with no
 *  editor of its own. Renders nothing when no host provides it. */
export function SchemaForm(props: SchemaFormProps) {
  const { SchemaForm: Host } = useProvided();
  return Host ? <Host {...props} /> : null;
}

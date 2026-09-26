import { Slot, SlotId } from "./slots";
import { TextArea, Select } from "./primitives";

/**
 * Host-provided components (RADD-1325).
 *
 * Some controls are too heavy to reimplement in the SDK and too host-specific to bundle into every
 * remote — a CodeMirror editor or the house token-list input.
 * The HOST provides its own at startup (`provideHostComponents`), and a remote renders them through
 * the wrappers below, which fall back to a plain control when a host provides none. So a plugin's
 * automation-node inspector looks and behaves like the host's own forms without shipping CodeMirror.
 */

export { provideHostComponents } from "./host-registry";
export type { HostComponents, CodeEditorProps, TokenListProps, SchemaFormProps, SettingsPageProps, SelectFieldProps } from "./host-registry";
import { useProvided, type CodeEditorProps, type TokenListProps, type SettingsPageProps, type SelectFieldProps, type CalloutProps, type DirectoryPagerProps, type ListSearchInputProps } from "./host-registry";
/** A code editor — the host's CodeMirror, else a monospace text area. */
export function CodeEditor(props: CodeEditorProps) {
  const { CodeEditor: Host } = useProvided();
  if (Host) return <Host {...props} />;
  return (
    <TextArea
      aria-label={props.ariaLabel ?? "Code"}
      readOnly={props.readOnly}
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

/** Shared page chrome and controls; these contracts carry no feature implementation. */
export function SettingsPage(props: SettingsPageProps) {
  const { SettingsPage: Host } = useProvided();
  return Host ? <Host {...props} /> : <section><h2>{props.title}</h2><p>{props.description}</p>{props.children}{props.history && <Slot id={SlotId.settingsFooter} history={props.history} />}</section>;
}
export function SelectField(props: SelectFieldProps) {
  const { SelectField: Host } = useProvided();
  if (Host) return <Host {...props} />;
  const { ariaLabel, hint: _hint, error: _error, onOpen: _onOpen, ...rest } = props;
  return <Select {...rest} aria-label={ariaLabel} />;
}
export const CalloutKind = { info: "info", success: "success", warning: "warning", danger: "danger" } as const;
export function Callout(props: CalloutProps) {
  const { Callout: Host } = useProvided();
  return Host ? <Host {...props} /> : <div role="note">{props.children}</div>;
}
export function QueryError(props: { label: string; error: unknown }) {
  const { QueryError: Host } = useProvided();
  return Host ? <Host {...props} /> : <p role="alert">Failed to load {props.label}: {String(props.error)}</p>;
}

export function DirectoryPager(props: DirectoryPagerProps) {
  const { DirectoryPager: Host } = useProvided();
  if (Host) return <Host {...props} />;
  return <nav aria-label={`${props.label} pagination`}>
    <button disabled={props.busy || props.page === 0} onClick={() => props.onPage(props.page - 1)}>Previous</button>
    <span>{props.page + 1}</span>
    <button disabled={props.busy || (props.page + 1) * props.pageSize >= props.total} onClick={() => props.onPage(props.page + 1)}>Next</button>
  </nav>;
}
export function ListSearchInput(props: ListSearchInputProps) {
  const { ListSearchInput: Host } = useProvided();
  return Host ? <Host {...props} /> : <input type="search" aria-label={props.ariaLabel ?? props.placeholder} placeholder={props.placeholder} value={props.value} onChange={event => props.onChange(event.target.value)} />;
}

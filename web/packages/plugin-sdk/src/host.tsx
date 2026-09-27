import { Slot, SlotId } from "./slots";
import { TextArea, Select } from "./primitives";
import { bridged } from "./bridge";
import { providedNow, ToastKind, type ToastKindValue } from "./host-registry";

/** Host-provided controls (CodeMirror, the token input, page chrome) — too heavy to bundle into every
 *  remote — rendered through these wrappers, each with a plain fallback. */

export { provideHostComponents } from "./host-registry";
export type { HostComponents, CodeEditorProps, TokenListProps, SchemaFormProps, SettingsPageProps, SelectFieldProps, ScopedSettingsProps, RoleGrantsProps, RoleGrantSubject, ToastKindValue } from "./host-registry";
export { ToastKind, CalloutKind, type CalloutKindValue } from "./host-registry";

/** A code editor — the host's CodeMirror, else a monospace text area. */
export const CodeEditor = bridged("CodeEditor", (props) => (
  <TextArea
    aria-label={props.ariaLabel ?? "Code"}
    readOnly={props.readOnly}
    value={props.value}
    onChange={(event) => props.onChange(event.target.value)}
    style={{ fontFamily: "monospace", minHeight: props.minHeight ?? 160 }}
  />
));

/** A list of short strings (answers, port names) — the host's token input, else one per line. */
export const TokenList = bridged("TokenList", (props) => (
  <TextArea
    aria-label={props.ariaLabel}
    placeholder={props.placeholder}
    value={props.value.join("\n")}
    onChange={(event) =>
      props.onChange(event.target.value.split("\n").map((line) => line.trim()).filter(Boolean))
    }
  />
));

/** Shared page chrome and controls; these contracts carry no feature implementation. */
export const SettingsPage = bridged("SettingsPage", (props) => (
  <section><h2>{props.title}</h2><p>{props.description}</p>{props.children}{props.history && <Slot id={SlotId.settingsFooter} history={props.history} />}</section>
));
export const SelectField = bridged("SelectField", (props) => {
  const { ariaLabel, hint: _hint, error: _error, onOpen: _onOpen, ...rest } = props;
  return <Select {...rest} aria-label={ariaLabel} />;
});
export const Callout = bridged("Callout", (props) => <div role="note">{props.children}</div>);
export const QueryError = bridged("QueryError", (props) => <p role="alert">Failed to load {props.label}: {String(props.error)}</p>);

export const DirectoryPager = bridged("DirectoryPager", (props) => (
  <nav aria-label={`${props.label} pagination`}>
    <button disabled={props.busy || props.page === 0} onClick={() => props.onPage(props.page - 1)}>Previous</button>
    <span>{props.page + 1}</span>
    <button disabled={props.busy || (props.page + 1) * props.pageSize >= props.total} onClick={() => props.onPage(props.page + 1)}>Next</button>
  </nav>
));
export const ListSearchInput = bridged("ListSearchInput", (props) => (
  <input type="search" aria-label={props.ariaLabel ?? props.placeholder} placeholder={props.placeholder} value={props.value} onChange={event => props.onChange(event.target.value)} />
));

/** One plugin's section of the settings cascade (RADD-1377). The editor, its effective/inherited
 *  display and Reset are the host's; the plugin names only the section it declared. */
export const ScopedSettings = bridged("ScopedSettings", (props) => <p role="note">Settings for “{props.section}” are unavailable.</p>);

/** A subject's role grants, as the Users and Teams pages show them. Renders nothing without a host. */
export const RoleGrants = bridged("RoleGrants", () => null);

/** Show a toast. Callable from mutation callbacks; a host without toasts logs instead. */
export function toast(message: string, kind: ToastKindValue = ToastKind.success): void {
  const { toast: host } = providedNow();
  if (host) host(message, kind);
  else console.info(`[${kind}] ${message}`);
}

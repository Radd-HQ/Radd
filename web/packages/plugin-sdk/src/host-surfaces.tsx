/** Shell surfaces a plugin draws with (SLQ editor, top-bar filter, view picker, sharing editor,
 *  report cards, issue links and peek). Each falls back to something plain, never a broken page. */
import { useEffect } from "react";
import { TextArea } from "./primitives";
import { Callout } from "./host";
import { bridged } from "./bridge";
import { useProvided, type SlqFieldProps } from "./host-registry";

/** An SLQ query field — the host's editor with autocomplete, else a plain text area. */
export function SlqField(props: SlqFieldProps) {
  const { SlqField: Host } = useProvided();
  const { onValidity } = props;
  // Without the host's validator nothing is known to be invalid; the server re-checks on save.
  useEffect(() => { if (!Host) onValidity?.(true); }, [Host, onValidity]);
  if (Host) return <Host {...props} />;
  return (
    <TextArea
      aria-label={props.label}
      placeholder={props.placeholder}
      value={props.value}
      onChange={(event) => props.onChange(event.target.value)}
      style={{ fontFamily: "monospace" }}
    />
  );
}

/** The page's SLQ filter in the top bar; without a shell there is no filter. */
export const PageQueryFilter = bridged("PageQueryFilter", (props) => <>{props.children("")}</>);

export const ViewSelect = bridged("ViewSelect", () => <p role="note">Saved views are unavailable.</p>);

export const SharingDialog = bridged("SharingDialog", () => null);

export const ReportWidget = bridged("ReportWidget", (props) => <p role="note">{props.title ?? "This report"} is unavailable.</p>);

export const ItemKeyLink = bridged("ItemKeyLink", (props) => <a href={`/issues/${props.itemKey}`} className={props.className}>{props.itemKey}</a>);

/** `children(open)` — `open` shows the issue in the peek panel (the full page without a shell). */
export const ItemPeek = bridged("ItemPeek", (props) => <>{props.children(() => window.location.assign(`/issues/${props.itemKey}`))}</>);

/** A suggested issue as a list row (`<li>`); render a list of them inside a `<ul>`. */
export const IssueSuggestion = bridged("IssueSuggestion", (props) => (
  <li>
    <a href={`/issues/${props.itemKey}`}>{props.itemKey} {props.title}</a> {props.badge}
    {props.note && <p>{props.note}</p>}
  </li>
));

export const MissingPluginType = bridged("MissingPluginType", (props) => (
  <Callout kind="warning" data-plugin-missing={props.disabled ? undefined : props.kind}>
    {props.disabled ? `This ${props.kind} has been turned off.` : `The “${props.typeKey}” ${props.kind} type is no longer available.`}
  </Callout>
));

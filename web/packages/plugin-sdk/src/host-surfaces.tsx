/**
 * Shell surfaces a plugin draws with (RADD-1393): the host's SLQ editor and top-bar filter, its
 * saved-view picker and sharing editor, its report cards, and issue links + the peek panel.
 *
 * Each wrapper renders the component the host provided at startup (`provideHostComponents`) and
 * falls back to something plain — never a broken page — where no host provides one (a remote's
 * own test harness). The contracts carry no implementation; the shell's stays the shell's.
 */
import { useEffect } from "react";
import { TextArea } from "./primitives";
import { Callout } from "./host";
import {
  useProvided,
  type IssueSuggestionProps,
  type ItemKeyLinkProps,
  type ItemPeekProps,
  type MissingPluginTypeProps,
  type PageQueryFilterProps,
  type ReportWidgetProps,
  type SharingDialogProps,
  type SlqFieldProps,
  type ViewSelectProps,
} from "./host-registry";

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
export function PageQueryFilter(props: PageQueryFilterProps) {
  const { PageQueryFilter: Host } = useProvided();
  return Host ? <Host {...props} /> : <>{props.children("")}</>;
}

export function ViewSelect(props: ViewSelectProps) {
  const { ViewSelect: Host } = useProvided();
  return Host ? <Host {...props} /> : <p role="note">Saved views are unavailable.</p>;
}

export function SharingDialog(props: SharingDialogProps) {
  const { SharingDialog: Host } = useProvided();
  return Host ? <Host {...props} /> : null;
}

export function ReportWidget(props: ReportWidgetProps) {
  const { ReportWidget: Host } = useProvided();
  return Host ? <Host {...props} /> : <p role="note">{props.title ?? "This report"} is unavailable.</p>;
}

export function ItemKeyLink(props: ItemKeyLinkProps) {
  const { ItemKeyLink: Host } = useProvided();
  return Host ? <Host {...props} /> : <a href={`/issues/${props.itemKey}`} className={props.className}>{props.itemKey}</a>;
}

/** `children(open)` — `open` shows the issue in the peek panel (the full page without a shell). */
export function ItemPeek(props: ItemPeekProps) {
  const { ItemPeek: Host } = useProvided();
  return Host ? <Host {...props} /> : <>{props.children(() => window.location.assign(`/issues/${props.itemKey}`))}</>;
}

/** A suggested issue as a list row (`<li>`); render a list of them inside a `<ul>`. */
export function IssueSuggestion(props: IssueSuggestionProps) {
  const { IssueSuggestion: Host } = useProvided();
  if (Host) return <Host {...props} />;
  return (
    <li>
      <a href={`/issues/${props.itemKey}`}>{props.itemKey} {props.title}</a> {props.badge}
      {props.note && <p>{props.note}</p>}
    </li>
  );
}

export function MissingPluginType(props: MissingPluginTypeProps) {
  const { MissingPluginType: Host } = useProvided();
  if (Host) return <Host {...props} />;
  return (
    <Callout kind="warning" data-plugin-missing={props.disabled ? undefined : props.kind}>
      {props.disabled ? `This ${props.kind} has been turned off.` : `The “${props.typeKey}” ${props.kind} type is no longer available.`}
    </Callout>
  );
}

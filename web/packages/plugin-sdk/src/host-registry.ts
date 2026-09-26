import { useSyncExternalStore, type ComponentType, type ReactNode, type ChangeEventHandler, type ButtonHTMLAttributes, type InputHTMLAttributes, type HTMLAttributes } from "react";
import type { DocumentHost } from "./host-document";
import type { CommentHost } from "./host-comments";
import type { KitHost } from "./host-kit";

export interface CodeEditorProps {
  value: string;
  onChange: (value: string) => void;
  /** e.g. "python". */
  language?: string;
  ariaLabel?: string;
  readOnly?: boolean;
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

export interface SettingsPageProps {
  title: string;
  description?: string;
  actions?: ReactNode;
  info?: ReactNode;
  history?: { entities?: string[]; projectId?: string };
  children: ReactNode;
}
export interface SelectFieldProps {
  label: string; hint?: string; error?: string; value?: string | number;
  onChange?: ChangeEventHandler<HTMLSelectElement>; onOpen?: () => void;
  disabled?: boolean; title?: string; id?: string; ariaLabel?: string;
  className?: string; children?: ReactNode;
}
export type ButtonVariantValue = "primary" | "secondary" | "ghost" | "danger" | "danger-ghost";
interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> { variant?: ButtonVariantValue; size?: "sm" | "md" }
interface FieldProps extends InputHTMLAttributes<HTMLInputElement> { label?: string; hint?: string; error?: string }
export interface CalloutProps extends HTMLAttributes<HTMLDivElement> {
  kind: "info" | "success" | "warning" | "danger"; children: ReactNode;
  /** Replaces the kind's icon; null shows none. */
  icon?: ComponentType<{ size?: number; className?: string; "aria-hidden"?: boolean }> | null;
}
export interface ModalProps { title?: string; onClose: () => void; children: ReactNode; wide?: boolean; extraWide?: boolean }
export interface DirectoryPagerProps { page: number; pageSize: number; total: number; busy: boolean; onPage: (page: number) => void; label: string }
export interface ListSearchInputProps { value: string; onChange: (next: string) => void; placeholder: string; ariaLabel?: string; total?: number; matched: number; noun: string; className?: string }
/** Shared person-avatar presentation; status data is contributed independently. */
interface AvatarProps {
  user: {id: string; name: string; avatar_color?: string | null; avatar_emoji?: string | null; avatar_url?: string | null};
  size?: "xs" | "sm" | "md" | "lg"; className?: string; title?: string;
}
/** One plugin's section of the settings cascade — the `section` it declared, and anything under it. */
export interface ScopedSettingsProps {
  scope: "instance" | "project";
  /** The project id, at project scope. */
  scopeId?: string;
  section: string;
  /** Grey the editors out (e.g. directory settings before a bind account exists). */
  disabled?: boolean;
  /** Shown when the section has no rows at this scope. */
  emptyLabel?: string;
}
/** Whose role grants to list and edit. */
export type RoleGrantSubject = { userId: string } | { teamId: string } | { groupId: string };
export interface RoleGrantsProps { subject: RoleGrantSubject; canManage: boolean }
/** An SLQ query field with the host's autocomplete and live validation (RADD-1393). */
export interface SlqFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  /** Narrows autocomplete and validation to one project's fields and states. */
  projectId?: string;
  placeholder?: string;
  /** Whether the draft parses — a form holds Save until it does. */
  onValidity?: (valid: boolean) => void;
}
/** The page's SLQ filter, in the shell's top bar. `children` receives the COMMITTED query. */
export interface PageQueryFilterProps {
  placeholder?: string;
  children: (committed: string) => ReactNode;
}
/** Pick one saved view the reader can see. */
export interface ViewSelectProps {
  value: string;
  onChange: (viewId: string) => void;
  label?: string;
}
/** The body a shared resource's save endpoint takes (the spec-57 model views and dashboards share).
 *  `grants` is the host's draft of grant changes; the plugin posts it as it comes. */
export interface SharedResourceSave {
  sharing: { global_access: string | null };
  grants: unknown;
  transfer_to?: string;
  expected_owner_id: string | null;
  expected_global_access: string | null;
}
/** Share a resource: server-wide access, per-person/team grants, ownership transfer. The host owns
 *  the editor and the grant diff; the plugin owns its endpoint (`onSave`). */
export interface SharingDialogProps {
  title: string;
  /** The access-grant resource type. */
  resourceType: "view" | "dashboard";
  resourceId: string;
  ownerId: string | null;
  globalAccess: string | null;
  /** May grant server-wide access. */
  canBroadcast: boolean;
  onSave: (body: SharedResourceSave) => Promise<unknown>;
  onClose: () => void;
}
/** One of the host's report cards, drawn as a dashboard widget of that report's type. */
export interface ReportWidgetProps {
  widgetType: string;
  config: Record<string, unknown>;
  title?: string | null;
  /** The dashboard-wide SLQ filter the report intersects with. */
  filterQuery?: string;
}
/** An issue key that links to the issue. */
export interface ItemKeyLinkProps { itemKey: string; className?: string }
/** Opens an issue in the shell's peek panel: `children` receives the opener. */
export interface ItemPeekProps { itemKey: string; children: (open: () => void) => ReactNode }
/** One suggested issue in a list (RADD-1395): its key and title link — opening in the peek panel
 *  when there is one, so a half-typed draft survives — and a preview on a resting pointer. */
export interface IssueSuggestionProps {
  itemKey: string;
  title: string;
  /** Beside the link: a score, a status. */
  badge?: ReactNode;
  /** A line under it: why it was suggested. */
  note?: ReactNode;
  /** Offer merging THIS issue (its id) into the suggestion — the reader is looking at a duplicate. */
  mergeFrom?: string;
  /** The row's link opened the issue, or a merge landed; a popover hosting the list may close. */
  onOpen?: () => void;
}
/** Where a contributed type or page cannot render: its plugin is gone, or it was turned off. */
export interface MissingPluginTypeProps { typeKey: string; kind: "view" | "widget" | "page"; disabled?: boolean }
export const ToastKind = { success: "success", error: "error" } as const;
export type ToastKindValue = (typeof ToastKind)[keyof typeof ToastKind];

/** Everything the host provides. The document, comment and kit families are declared beside their
 *  wrappers (RADD-1392). */
export interface HostComponents extends DocumentHost, CommentHost, KitHost {
  Avatar?: ComponentType<AvatarProps>;
  DirectoryPager?: ComponentType<DirectoryPagerProps>;
  ListSearchInput?: ComponentType<ListSearchInputProps>;
  Modal?: ComponentType<ModalProps>;
  Button?: ComponentType<ButtonProps>;
  TextField?: ComponentType<FieldProps>;
  SelectField?: ComponentType<SelectFieldProps>;
  SettingsPage?: ComponentType<SettingsPageProps>;
  Callout?: ComponentType<CalloutProps>;
  QueryError?: ComponentType<{label: string; error: unknown}>;

  /** The settings cascade editor (specs 50/67), scoped to one plugin's section. */
  ScopedSettings?: ComponentType<ScopedSettingsProps>;
  /** A subject's role grants — the Users/Teams section, for a plugin's own subjects. */
  RoleGrants?: ComponentType<RoleGrantsProps>;
  /** The host's toast. A function, not a component: mutations call it from callbacks. */
  toast?: (message: string, kind: ToastKindValue) => void;

  CodeEditor?: ComponentType<CodeEditorProps>;
  TokenList?: ComponentType<TokenListProps>;

  // Shell surfaces (SLQ editor, top bar, view picker, sharing, reports, issue links, peek).
  SlqField?: ComponentType<SlqFieldProps>;
  PageQueryFilter?: ComponentType<PageQueryFilterProps>;
  ViewSelect?: ComponentType<ViewSelectProps>;
  SharingDialog?: ComponentType<SharingDialogProps>;
  ReportWidget?: ComponentType<ReportWidgetProps>;
  ItemKeyLink?: ComponentType<ItemKeyLinkProps>;
  ItemPeek?: ComponentType<ItemPeekProps>;
  MissingPluginType?: ComponentType<MissingPluginTypeProps>;
  IssueSuggestion?: ComponentType<IssueSuggestionProps>;
}

let provided: HostComponents = {};
const listeners = new Set<() => void>();

/** Called once by the host at startup. */
export function provideHostComponents(components: HostComponents): void {
  provided = { ...provided, ...components };
  for (const listener of listeners) listener();
}

/** The current provision, outside React (for callbacks). */
export function providedNow(): HostComponents {
  return provided;
}

export function useProvided(): HostComponents {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => provided,
  );
}


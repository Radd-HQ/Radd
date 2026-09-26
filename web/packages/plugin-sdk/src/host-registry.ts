import { useSyncExternalStore, type ComponentType, type ReactNode, type ChangeEventHandler, type ButtonHTMLAttributes, type InputHTMLAttributes, type HTMLAttributes } from "react";

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
export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> { variant?: ButtonVariantValue; size?: "sm" | "md" }
export interface FieldProps extends InputHTMLAttributes<HTMLInputElement> { label?: string; hint?: string; error?: string }
export interface CalloutProps extends HTMLAttributes<HTMLDivElement> { kind: "info" | "success" | "warning" | "danger"; children: ReactNode }
export interface ModalProps { title?: string; onClose: () => void; children: ReactNode; wide?: boolean; extraWide?: boolean }
export interface DirectoryPagerProps { page: number; pageSize: number; total: number; busy: boolean; onPage: (page: number) => void; label: string }
export interface ListSearchInputProps { value: string; onChange: (next: string) => void; placeholder: string; ariaLabel?: string; total?: number; matched: number; noun: string; className?: string }
/** Shared person-avatar presentation; status data is contributed independently. */
export interface AvatarProps {
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
export const ToastKind = { success: "success", error: "error" } as const;
export type ToastKindValue = (typeof ToastKind)[keyof typeof ToastKind];

export interface HostComponents {
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
  SchemaForm?: ComponentType<SchemaFormProps>;
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


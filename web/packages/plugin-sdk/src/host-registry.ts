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
export interface HostComponents {
  DirectoryPager?: ComponentType<DirectoryPagerProps>;
  ListSearchInput?: ComponentType<ListSearchInputProps>;
  Modal?: ComponentType<ModalProps>;
  Button?: ComponentType<ButtonProps>;
  TextField?: ComponentType<FieldProps>;
  SelectField?: ComponentType<SelectFieldProps>;
  SettingsPage?: ComponentType<SettingsPageProps>;
  Callout?: ComponentType<CalloutProps>;
  QueryError?: ComponentType<{label: string; error: unknown}>;

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

export function useProvided(): HostComponents {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => provided,
  );
}


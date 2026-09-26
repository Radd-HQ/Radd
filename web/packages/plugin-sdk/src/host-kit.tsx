import { useEffect, type ComponentType, type ReactNode, type Ref } from "react";
import { bridged } from "./bridge";
import { providedNow } from "./host-registry";

/** The host's menus, Escape stack, access editors, state dot and sidebar section chrome, bridged. */

type IconType = ComponentType<{ size?: number; className?: string; "aria-hidden"?: boolean }>;

export type MenuItem =
  | { kind: "action"; label: string; icon?: IconType; onSelect: () => void; danger?: boolean; disabled?: boolean }
  | { kind: "separator" };

export interface MenuTriggerProps {
  ref: Ref<HTMLButtonElement>;
  open: boolean;
  toggle: () => void;
}

export interface DropdownMenuProps {
  items: MenuItem[];
  /** aria-label for the trigger and the menu. */
  label: string;
  align?: "start" | "end";
  side?: "bottom" | "top";
  /** Panel width utility (default w-48). */
  widthClass?: string;
  className?: string;
  /** Custom trigger; defaults to a ⋯ icon button. */
  trigger?: (props: MenuTriggerProps) => ReactNode;
}

export interface PopoverProps {
  open: boolean;
  onClose: () => void;
  /** Accessible name for the panel. */
  label: string;
  align?: "start" | "end";
  /** Panel width/padding/scrolling; the frame is the popover's. */
  className?: string;
  children: ReactNode;
}

/** The generic spec-92 grants editor for one resource. */
export interface AccessGrantsEditorProps {
  resourceType: string;
  resourceId: string;
  description?: ReactNode;
}

/** The role grants scoped to one space or project. */
export interface ScopedAccessProps {
  kind: "space" | "project";
  scopeId: string;
  scopeName: string;
  canGrant: boolean;
  canRevoke: boolean;
  canRenew: boolean;
}

/** One folding section of the left sidebar, with its bounded search + pager when given one. */
export interface SidebarSectionProps {
  label: string;
  /** When set, the label navigates; the chevron still folds. */
  labelTo?: string;
  collapsed: boolean;
  onToggle: () => void;
  /** Stays clickable while collapsed (a manage link). */
  actions?: ReactNode;
  directory?: {
    filter: string; setFilter: (value: string) => void; total: number; page: number; pageSize: number;
    busy: boolean; isError: boolean; error: unknown; setPage: (page: number) => void; refetch?: () => unknown;
  };
  /** The directory's noun ("wiki spaces"). */
  directoryLabel?: string;
  children: ReactNode;
}

/** A sidebar destination, styled and active-marked like the host's own rows. */
export interface SidebarLinkProps {
  to: string;
  params?: Record<string, string>;
  children: ReactNode;
}

/** What the host provides from its kit. */
export interface KitHost {
  DropdownMenu?: ComponentType<DropdownMenuProps>;
  Popover?: ComponentType<PopoverProps>;
  AccessGrantsEditor?: ComponentType<AccessGrantsEditorProps>;
  ScopedAccess?: ComponentType<ScopedAccessProps>;
  StateCategoryDot?: ComponentType<{ category: string }>;
  SidebarSection?: ComponentType<SidebarSectionProps>;
  SidebarLink?: ComponentType<SidebarLinkProps>;
  /** Register an Escape handler on the host's one stack (topmost first); returns the unregister. */
  registerDismiss?: (handler: () => boolean) => () => void;
}

export const DropdownMenu = bridged("DropdownMenu", () => null);

export const Popover = bridged("Popover", (props) =>
  props.open ? <div role="dialog" aria-label={props.label} className={props.className}>{props.children}</div> : null);

export const AccessGrantsEditor = bridged("AccessGrantsEditor", () => <p role="note">Access editing is unavailable.</p>);

export const ScopedAccess = bridged("ScopedAccess", () => null);

/** The workflow-state category's colour dot (triage, todo, done, …). */
export const StateCategoryDot = bridged("StateCategoryDot", () => null);

export const SidebarSection = bridged("SidebarSection", (props) =>
  <section aria-label={props.label}>{props.collapsed ? null : props.children}</section>);

export const SidebarLink = bridged("SidebarLink", (props) => <a href={props.to}>{props.children}</a>);

/** Close on Escape through the host's dismiss stack, so the topmost surface closes first. */
export function useDismiss(onDismiss: () => void, active = true): void {
  useEffect(() => {
    if (!active) return;
    const register = providedNow().registerDismiss;
    if (register) return register(() => { onDismiss(); return true; });
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onDismiss(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onDismiss, active]);
}

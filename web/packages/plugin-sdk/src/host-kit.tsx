import { useEffect, type ComponentType, type ReactNode, type Ref } from "react";
import { providedNow, useProvided } from "./host-registry";

/**
 * More of the host's kit, bridged (RADD-1392): the action menu and click-away popover every
 * surface shares, the Escape stack, the access editors, the workflow-state dot and the left
 * sidebar's section chrome. Each is host code other host surfaces use; the host provides them at
 * startup and a plugin renders them through these contracts.
 */

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

export function DropdownMenu(props: DropdownMenuProps) {
  const { DropdownMenu: Host } = useProvided();
  return Host ? <Host {...props} /> : null;
}

export function Popover(props: PopoverProps) {
  const { Popover: Host } = useProvided();
  if (Host) return <Host {...props} />;
  return props.open ? <div role="dialog" aria-label={props.label} className={props.className}>{props.children}</div> : null;
}

export function AccessGrantsEditor(props: AccessGrantsEditorProps) {
  const { AccessGrantsEditor: Host } = useProvided();
  return Host ? <Host {...props} /> : <p role="note">Access editing is unavailable.</p>;
}

export function ScopedAccess(props: ScopedAccessProps) {
  const { ScopedAccess: Host } = useProvided();
  return Host ? <Host {...props} /> : null;
}

/** The workflow-state category's colour dot (triage, todo, done, …). */
export function StateCategoryDot(props: { category: string }) {
  const { StateCategoryDot: Host } = useProvided();
  return Host ? <Host {...props} /> : null;
}

export function SidebarSection(props: SidebarSectionProps) {
  const { SidebarSection: Host } = useProvided();
  if (Host) return <Host {...props} />;
  return <section aria-label={props.label}>{props.collapsed ? null : props.children}</section>;
}

export function SidebarLink(props: SidebarLinkProps) {
  const { SidebarLink: Host } = useProvided();
  return Host ? <Host {...props} /> : <a href={props.to}>{props.children}</a>;
}

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

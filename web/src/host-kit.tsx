/**
 * More of the host's kit, handed to the plugin SDK (RADD-1392): the menus, the Escape stack, the
 * access editors, the state dot and the sidebar's section chrome — what the wiki (the pages
 * plugin's bundled UI) renders beside the host's own surfaces. The access editors stay lazy.
 */
import { Suspense, lazy } from "react";
import { Link } from "@tanstack/react-router";
import { provideHostComponents } from "@radd/plugin-sdk";
import { DropdownMenu } from "./components/DropdownMenu";
import { Popover } from "./components/Popover";
import { registerDismiss } from "./lib/dismiss-stack";
import { CATEGORY_META } from "./lib/meta";
import type { StateCategoryValue } from "./lib/types";
import { SidebarDirectory } from "./components/shell/SidebarDirectory";
import { navLinkClasses, SectionHeader } from "./components/shell/SidebarRows";

const AccessGrantsEditor = lazy(() =>
  import("./components/settings/AccessGrantsEditor").then((module) => ({ default: module.AccessGrantsEditor })),
);
const ScopedAccessPanel = lazy(() =>
  import("./components/settings/ScopedAccessPanel").then((module) => ({ default: module.ScopedAccessPanel })),
);

provideHostComponents({
  DropdownMenu,
  Popover,
  registerDismiss,
  AccessGrantsEditor: (props) => <Suspense fallback={null}><AccessGrantsEditor {...props} /></Suspense>,
  ScopedAccess: (props) => <Suspense fallback={null}><ScopedAccessPanel {...props} /></Suspense>,
  StateCategoryDot: ({ category }) => (
    <span
      className={"size-2 rounded-full " + (CATEGORY_META[category as StateCategoryValue]?.dotClassName ?? "bg-fg-faint")}
      aria-hidden
    />
  ),
  SidebarSection: ({ label, labelTo, collapsed, onToggle, actions, directory, directoryLabel, children }) => (
    <div className="mt-3">
      <SectionHeader label={label} labelTo={labelTo} collapsed={collapsed} onToggle={onToggle} actions={actions} />
      {!collapsed && (directory
        ? <SidebarDirectory directory={directory} label={directoryLabel ?? label}>{children}</SidebarDirectory>
        : children)}
    </div>
  ),
  // `to` is a route path the plugin owns; the router still type-checks the host's own links.
  SidebarLink: ({ to, params, children }) => (
    <Link to={to as never} params={params as never} className={navLinkClasses}>{children}</Link>
  ),
});

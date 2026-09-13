import { useIsAuthenticated } from "../../lib/hooks";
import { useState, type ReactNode } from "react";
import { Clock, GitBranch, History, MessageSquare, type LucideIcon } from "lucide-react";
import { useSlot, SlotId } from "@radd/plugin-sdk";
import type { Item, Project } from "../../lib/types";
import { CommentsThread } from "./CommentsThread";
import { HistoryTab } from "./HistoryTab";
import { VcsPanel } from "./VcsPanel";
import { WorklogTab } from "./WorklogTab";

const ActivityTab = {
  comments: "comments",
  history: "history",
  worklog: "worklog",
  vcs: "vcs",
} as const;

interface PanelTab {
  key: string;
  label: ReactNode;
  icon: ReactNode;
  count?: number;
  render: () => ReactNode;
}

/**
 * The item's Activity area (redesign): the Comments thread plus History (field
 * changes / audit), Work log (logged-work history), and Version control tabs —
 * the "everything that happened to this issue" panel, replacing the standalone
 * comments section.
 */
export function ActivityPanel({
  item,
  project,
  timeloggingEnabled,
}: {
  item: Item;
  project: Project;
  timeloggingEnabled: boolean;
}) {
  const [tab, setTab] = useState<string>(ActivityTab.comments);
  const authenticated = useIsAuthenticated();

  // Plugin-contributed Activity tabs (spec 94): a plugin adds a tab next to VCS by registering an
  // `issue.tab` slot — its `title`/`icon` drive the tab button, its `render` the panel body. This
  // component owns no plugin knowledge.
  const pluginTabs = useSlot(SlotId.issueTab).map((entry) => ({
    key: `${entry.plugin}:${entry.contribution.id}`,
    label: entry.contribution.title ?? "Tab",
    icon: entry.contribution.icon ?? null,
    render: () => entry.contribution.render({ item, project }),
  }));

  const builtinIcon = (Icon: LucideIcon) => <Icon size={14} aria-hidden />;
  const tabs: PanelTab[] = [
    { key: ActivityTab.comments, label: "Comments", icon: builtinIcon(MessageSquare), count: item.comment_count, render: () => <CommentsThread item={item} project={project} /> },
    { key: ActivityTab.history, label: "History", icon: builtinIcon(History), render: () => <HistoryTab itemId={item.id} /> },
    // RADD-1153: worklogs and version-control links are account-only reads —
    // a visitor gets no tab rather than a tab that errors (the spec-96 rule).
    ...(timeloggingEnabled && authenticated
      ? [{ key: ActivityTab.worklog, label: "Work log", icon: builtinIcon(Clock), render: () => <WorklogTab itemId={item.id} /> } satisfies PanelTab]
      : []),
    ...(authenticated
      ? [{ key: ActivityTab.vcs, label: "Version control", icon: builtinIcon(GitBranch), render: () => <VcsPanel item={item} project={project} /> } satisfies PanelTab]
      : []),
    ...pluginTabs,
  ];
  const active = tabs.find((t) => t.key === tab) ?? tabs[0];

  return (
    <div>
      <div role="tablist" aria-label="Activity" className="flex flex-wrap gap-1 border-b border-subtle">
        {tabs.map(({ key, label, icon, count }) => {
          const isActive = active.key === key;
          return (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => setTab(key)}
              className={
                "-mb-px flex items-center gap-1.5 border-b-2 px-2.5 py-2 text-[13px] cursor-pointer " +
                (isActive
                  ? "border-accent-hover text-heading"
                  : "border-transparent text-fg-muted hover:text-fg")
              }
            >
              {icon}
              {label}
              {typeof count === "number" ? <span className="text-fg-faint">{count}</span> : null}
            </button>
          );
        })}
      </div>

      <div className="pt-4">{active.render()}</div>
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { CheckCircle2, ChevronRight, MinusCircle } from "lucide-react";
import { RoutePath } from "../../lib/constants";
import { capabilitiesQuery } from "../../lib/queries";
import type { CapabilitiesManifest } from "../../lib/types";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { Spinner } from "../../components/Spinner";
import { QueryError } from "../../components/QueryError";
import { settingsPathForPlugin } from "./layout";

/** A read-only enabled/disabled (or value) badge for one deploy subsystem.
 * `detail` adds a muted sub-status; `to` makes the row a link to its settings
 * surface — the status rows ARE the navigation for deploy-level config (user
 * direction). */
function StatusPill({
  label,
  on,
  value,
  detail,
  to,
}: {
  label: string;
  on?: boolean;
  value?: string;
  detail?: string;
  to?: string;
}) {
  const active = on ?? Boolean(value);
  const body = (
    <>
      <span className="flex min-w-0 items-center gap-2">
        <span className="truncate text-xs text-fg">{label}</span>
        {detail && <span className="truncate text-[11px] text-fg-faint">{detail}</span>}
      </span>
      <span
        className={
          "inline-flex shrink-0 items-center gap-1 text-[11px] " +
          (active ? "text-status-success-ink" : "text-fg-faint")
        }
      >
        {active ? <CheckCircle2 size={12} aria-hidden /> : <MinusCircle size={12} aria-hidden />}
        {value || (active ? "On" : "Off")}
        {to && <ChevronRight size={12} className="text-fg-muted" aria-hidden />}
      </span>
    </>
  );
  const frame = "flex items-center justify-between rounded-md border border-subtle px-3 py-2";
  if (to) {
    return (
      <Link
        to={to}
        className={`${frame} transition-colors hover:border-emphasis hover:bg-surface/60`}
        title="Open settings"
        data-status-row={label}
      >
        {body}
      </Link>
    );
  }
  return <div className={frame} data-status-row={label}>{body}</div>;
}

/** Rows in this order; a category nobody lists here sorts after them. Connectors fold into one row. */
const CATEGORY_ORDER = ["infra", "auth", "storage", "ai", "feature"];
const CONNECTOR = "connector";
const HOST_OWNED: Record<string, string> = { attachments: RoutePath.settingsStorage };

/**
 * Every capability the loaded plugins report (RADD-1389). The page used to render a fixed schema
 * that named SSO, LDAP, SMTP and AI, so the core had to know every optional plugin and a mail
 * setup made of sender rows read Off. Now each plugin says what it is and how it is doing; the row
 * links wherever its plugin's settings live, and a disabled plugin has no row at all.
 */
function StatusGrid({ manifest }: { manifest: CapabilitiesManifest }) {
  const rows = manifest.capabilities
    .filter((cap) => cap.category !== CONNECTOR)
    .sort((a, b) => rank(a.category) - rank(b.category) || a.label.localeCompare(b.label));
  const connectors = manifest.capabilities.filter((cap) => cap.category === CONNECTOR);
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {rows.map((cap) => (
        <StatusPill
          key={cap.key}
          label={cap.label}
          on={cap.enabled}
          detail={typeof cap.detail?.summary === "string" ? cap.detail.summary : undefined}
          to={cap.plugin ? (HOST_OWNED[cap.plugin] ?? settingsPathForPlugin(cap.plugin, manifest)?.to) : undefined}
        />
      ))}
      {/* Per-connector status lives on Settings → Plugins; the deploy dashboard keeps one
          at-a-glance count that links there (reorg 2026-08-01). */}
      {connectors.length > 0 && (
        <StatusPill
          label="Connectors"
          value={`${connectors.filter((cap) => cap.enabled).length} of ${connectors.length} configured`}
          to={RoutePath.settingsPlugins}
        />
      )}
    </div>
  );
}

function rank(category: string): number {
  const index = CATEGORY_ORDER.indexOf(category);
  return index === -1 ? CATEGORY_ORDER.length : index;
}

/**
 * Server status (spec 50; status-only since spec 67; generic since RADD-1389) — instance-admin
 * only (the tab is hidden otherwise). Shows what each loaded plugin reports as set up. The editable
 * product defaults live on the General tab; secrets are configured via environment variables only.
 */
export function InstanceSettingsPage() {
  // Fresh on every visit: a plugin page's write cannot name this query, and a status page that
  // lags the change you just made reads as the change not working.
  const manifest = useQuery({ ...capabilitiesQuery, refetchOnMount: "always" });
  return (
    <SettingsPage history={{ entities: ["plugin", "scoped_setting"] }}
      title="Server status"
      description="What this server is running and whether each piece is set up. Click a row to configure it; product defaults for every project live under General."
    >
      <section>
        <h2 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-muted">
          Deploy status
        </h2>
        {manifest.isPending ? (
          <Spinner label="Loading status…" />
        ) : manifest.isError ? (
          <QueryError label="status" error={manifest.error} />
        ) : (
          <StatusGrid manifest={manifest.data} />
        )}
      </section>
    </SettingsPage>
  );
}

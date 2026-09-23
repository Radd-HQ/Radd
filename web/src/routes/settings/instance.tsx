import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { CheckCircle2, ChevronRight, MinusCircle } from "lucide-react";
import { RoutePath } from "../../lib/constants";
import { instanceStatusQuery } from "../../lib/queries";
import { type InstanceStatus } from "../../lib/types";
import { SettingsPage } from "../../components/settings/SettingsPage";
import { Spinner } from "../../components/Spinner";
import { QueryError } from "../../components/QueryError";

/** A read-only enabled/disabled (or value) badge for one deploy subsystem
 * (shared with the Directory page's status card, spec 85). `detail` adds a
 * muted sub-status; `to` makes the row a link to its settings surface — the
 * status rows ARE the navigation for deploy-level config (user direction). */
export function StatusPill({
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
          (active ? "text-emerald-400" : "text-fg-faint")
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
      >
        {body}
      </Link>
    );
  }
  return <div className={frame}>{body}</div>;
}

function StatusGrid({ status }: { status: InstanceStatus }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      <StatusPill label="OIDC SSO" on={status.sso_enabled} />
      {/* ONE directory row (bind account folded in as detail); clicking opens
          the consolidated Directory settings (spec 85). */}
      <StatusPill
        label="LDAP / AD"
        on={status.ldap_enabled}
        detail={status.ldap_bind_account ? "bind account on" : "no bind account"}
        to={RoutePath.settingsDirectory}
      />
      {/* RADD-958: clicking opens Settings → Email. Mail is configured in the
          product now, not only in the environment. */}
      <StatusPill
        label="Email"
        on={status.smtp_configured}
        to={RoutePath.settingsEmail}
      />
      <StatusPill label="TOTP MFA" on={status.mfa_available} />
      {/* Clicking opens Settings → AI (spec 101) — providers/roles/toggles live there. */}
      <StatusPill
        label="AI provider"
        value={status.ai_provider || "Off"}
        to={RoutePath.settingsAi}
      />
      {/* Clicking opens Settings → Storage (spec 102) — hosts + delivery live there. */}
      <StatusPill
        label="Attachment storage"
        value={status.attachment_storage}
        to={RoutePath.settingsStorage}
      />
      <StatusPill label="Background workers" on={status.workers_enabled} />
      {/* Per-connector status lives on Settings → Plugins (each connector's
          row shows Configured/Not configured; reorg 2026-08-01) — the deploy
          dashboard keeps one at-a-glance count that links there. */}
      {Object.keys(status.connectors).length > 0 && (
        <StatusPill
          label="Connectors"
          value={`${Object.values(status.connectors).filter(Boolean).length} of ${
            Object.keys(status.connectors).length
          } configured`}
          to={RoutePath.settingsPlugins}
        />
      )}
    </div>
  );
}

/**
 * Server settings (spec 50; status-only since spec 67) — instance-admin only
 * (the tab is hidden otherwise, and the API 403s). Shows non-secret deploy
 * status: what's enabled, read from env. The editable product defaults live on
 * the General tab. Secrets are configured via environment variables only —
 * never editable here.
 */
export function InstanceSettingsPage() {
  const status = useQuery(instanceStatusQuery);
  return (
    <SettingsPage history={{ entities: ["plugin", "scoped_setting"] }}
      title="Server status"
      description="What this server is running and whether each piece is set up. Click a row to configure it; product defaults for every project live under General."
    >
      <section>
        <h2 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-fg-muted">
          Deploy status
        </h2>
        {status.isPending ? (
          <Spinner label="Loading status…" />
        ) : status.isError ? (
          <QueryError label="status" error={status.error} />
        ) : (
          <StatusGrid status={status.data} />
        )}
      </section>
    </SettingsPage>
  );
}

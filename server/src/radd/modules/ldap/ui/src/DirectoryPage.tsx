import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { EmptyState, QueryError, ScopedSettings, SettingsPage, Spinner, useCurrentUser } from "@radd/plugin-sdk";
import { GroupsTab } from "./GroupsTab";
import { deployStatusQuery } from "./queries";
import { StatusRow } from "./StatusRow";
import { sectionHeadClasses } from "./sync";
import { UserSyncTab } from "./UserSyncTab";

const DIRECTORY_TABS = [["connection", "Connection"], ["users", "User sync"], ["groups", "Groups"]] as const;
type DirectoryTab = (typeof DIRECTORY_TABS)[number][0];

/**
 * Settings → Directory (spec 85; the ldap plugin's own page since RADD-1381) — instance admins
 * only: deploy status, the connection, the automatic user sync (cascade-backed base + toggles,
 * "Sync now", last-run line, AD user import), and the group browser with the mirror table and its
 * role grants. The Users page keeps ACCOUNT administration.
 */
export function DirectorySettingsPage() {
  const [tab, setTab] = useState<DirectoryTab>("connection");
  const me = useCurrentUser();
  const isInstanceAdmin = me?.instance_role === "admin";
  const status = useQuery({ ...deployStatusQuery, enabled: isInstanceAdmin });
  const directoryReady = Boolean(status.data?.ldap_bind_account);

  return (
    <SettingsPage history={{ entities: ["group", "user", "scoped_setting"] }}
      title="Directory"
      description="Your LDAP or Active Directory: the connection, automatic user sync from a search base, and which directory groups link to teams."
    >
      {!me ? (
        <Spinner label="Loading…" />
      ) : !isInstanceAdmin ? (
        <EmptyState icon={Lock} message="Only instance admins can manage the directory." />
      ) : (
        <div className="flex flex-col gap-8" data-directory-page>
          <section>
            <h2 className={sectionHeadClasses}>Status</h2>
            {status.isPending ? (
              <Spinner label="Loading status…" />
            ) : status.isError ? (
              <QueryError label="status" error={status.error} />
            ) : (
              <div className="grid gap-2 sm:grid-cols-3">
                <StatusRow label="LDAP / AD sign-in" on={status.data.ldap_enabled} />
                <StatusRow label="Bind (service) account" on={status.data.ldap_bind_account} />
                <StatusRow label="Background workers" on={status.data.workers_enabled} />
              </div>
            )}
          </section>

          {/* RADD-1294: one page held the connection, user sync and every directory group at
              once (4,439 checkboxes on a real AD). */}
          <div role="tablist" aria-label="Directory" className="-mb-4 flex gap-1 border-b border-subtle">
            {DIRECTORY_TABS.map(([key, label]) => (
              <button key={key} type="button" role="tab" aria-selected={tab === key} data-directory-tab={key}
                onClick={() => setTab(key)}
                className={"-mb-px cursor-pointer border-b-2 px-2.5 py-2 text-[13px] " +
                  (tab === key ? "border-accent-hover text-heading" : "border-transparent text-fg-muted hover:text-fg")}>
                {label}
              </button>
            ))}
          </div>
          {tab === "connection" && (
            <section>
              <h2 className={sectionHeadClasses}>Connection</h2>
              {/* RADD-846: editable here and deliberately NOT gated on directoryReady — configuring
                  it is exactly what an unready instance needs. Env (RADD_LDAP_*) stays the seed. */}
              <ScopedSettings scope="instance" section="directory.connection" />
            </section>
          )}
          {tab === "users" && <UserSyncTab directoryReady={directoryReady} />}
          {tab === "groups" && <GroupsTab directoryReady={directoryReady} />}
        </div>
      )}
    </SettingsPage>
  );
}

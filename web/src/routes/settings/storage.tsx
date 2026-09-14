import { Lock } from "lucide-react";
import { useCurrentUser } from "../../lib/hooks";
import { InstanceRole } from "../../lib/types";
import { EmptyState } from "../../components/EmptyState";
import { HostsPanel } from "../../components/settings/storage/HostsPanel";
import { RuleChainPanel } from "../../components/settings/storage/RuleChainPanel";
import { SettingsPage } from "../../components/settings/SettingsPage";

/**
 * Settings → Storage (spec 102) — instance admins only (the API 403s otherwise).
 * Hosts: where attachment bytes can live and how they're delivered. Rules: the
 * routing chain that decides which host each upload lands on.
 */
export function StorageSettingsPage() {
  const me = useCurrentUser();
  const isInstanceAdmin = me?.instance_role === InstanceRole.admin;

  return (
    <SettingsPage history={{ entities: ["storage_host", "storage_rule"] }}
      title="Storage"
      description="Where attachment bytes live — filesystem roots and S3-compatible endpoints — and the routing chain that decides which host each upload lands on."
      info={
        <>
          Storage hosts are the places an upload can land; the routing chain decides which one.
          Each upload walks the rules top-down — the first that answers wins, everything else
          lands on the <strong>default</strong> host. Proxy delivery streams bytes through
          Radd; presigned delivery redirects the browser to fetch straight from the host — so
          network reachability decides who can read a presigned host&rsquo;s files.
        </>
      }
    >
      {!isInstanceAdmin ? (
        <EmptyState icon={Lock} message="Only instance admins can manage storage." />
      ) : (
        <>
          <HostsPanel />
          <RuleChainPanel />
        </>
      )}
    </SettingsPage>
  );
}

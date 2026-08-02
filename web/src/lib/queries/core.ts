/** Auth state, instance status/config, capabilities, plugins, and scoped settings. */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { fetchAuthState } from "../auth";
import {
  ApiPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  CapabilitiesManifest,
  InstanceConfig,
  InstanceStatus,
  Plugin,
  ResolvedSetting,
  ScopedSetting,
  SettingKeyValue,
  SettingScopeValue,
  TotpStatus,
} from "../types";

export const authStateQuery = queryOptions({
  queryKey: queryKeys.authState,
  queryFn: fetchAuthState,
  staleTime: 60_000,
  retry: false,
});

export const instanceStatusQuery = queryOptions({
  queryKey: ["instance-status"] as const,
  queryFn: () => api.get<InstanceStatus>(ApiPath.instanceStatus),
  staleTime: 60_000,
});

/** The backend-assembled UI manifest (spec 93 / A7): capability flags + plugin
 * nav. Drives the sidebar's plugin-contributed nav — chokepoint 3. */
export const capabilitiesQuery = queryOptions({
  queryKey: ["capabilities"] as const,
  queryFn: () => api.get<CapabilitiesManifest>(ApiPath.capabilities),
  staleTime: 60_000,
});

/** The plugin manager's plugin list (spec 93 / A4) — the Settings → Plugins page. */
export const pluginsQuery = queryOptions({
  queryKey: queryKeys.plugins,
  queryFn: () => api.get<Plugin[]>(ApiPath.plugins),
});

/** Scalar settings at a scope (spec 50). `scopeId` omitted for instance scope. */
export const scopedSettingsQuery = (scope: SettingScopeValue, scopeId?: string) =>
  queryOptions({
    queryKey: ["scoped-settings", scope, scopeId ?? null] as const,
    queryFn: () =>
      api.get<ScopedSetting[]>(ApiPath.scopedSettings, {
        query: scopeId ? { scope, scope_id: scopeId } : { scope },
      }),
  });

/** One key's cascade-RESOLVED value (spec 70): the project override if any, else
 * the instance override, else the default — readable by ANY member (the
 * manage-gated scope editors above use `scopedSettingsQuery` instead). */
export const resolvedSettingQuery = (key: SettingKeyValue, projectId?: string) =>
  queryOptions({
    queryKey: ["scoped-settings-resolved", key, projectId ?? null] as const,
    queryFn: () =>
      api.get<ResolvedSetting>(ApiPath.scopedSettingsResolve, {
        query: { key, project_id: projectId },
      }),
    staleTime: 60_000,
  });

/** Safe instance config — work week (spec 35) + timelog day/week lengths
 *  (spec 67, feeds useDurationConfig). Static per deployment. */
export const instanceConfigQuery = queryOptions({
  queryKey: ["instanceConfig"] as const,
  queryFn: () => api.get<InstanceConfig>(ApiPath.instance),
  staleTime: Infinity,
});

/** The caller's two-factor state (spec 48) — a plain query, no entity tags. */
export const totpStatusQuery = queryOptions({
  queryKey: queryKeys.totp,
  queryFn: () => api.get<TotpStatus>(ApiPath.totp),
  retry: false,
});

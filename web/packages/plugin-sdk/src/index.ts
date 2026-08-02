/**
 * @radd/plugin-sdk — the public frontend surface for Radd plugins (docs/plugin-platform.md §9).
 * The ONLY module a plugin's UI imports. Shared as a federation singleton so the slot registry,
 * primitives, hooks and theme are ONE instance across the host and every remote.
 */

export { UI_API_VERSION, isUiApiCompatible } from "./version";

export {
  SlotId,
  Slot,
  useSlot,
  useSlotMatch,
  registerSlot,
  unregisterSlot,
  unregisterPlugin,
  activeSlotPlugins,
  useActiveSlotPlugins,
  useDisabledNavPaths,
  useDisabledMatches,
  syncContributionPrefs,
  setUserContributionEnabled,
  setGlobalContributionEnabled,
  useUserContributionToggles,
  useGlobalContributionToggles,
  UserContributionToggles,
  GlobalContributionToggles,
  type SlotContribution,
  type SlotIdValue,
  type ContributionInfo,
  type ToggleScope,
} from "./slots";

export {
  definePlugin,
  type PluginContext,
  type PluginModule,
  type PluginContribution,
} from "./plugin";

export {
  Button,
  TextField,
  TextArea,
  Select,
  Chip,
  Card,
  Spinner,
  EmptyState,
  Modal,
  Avatar,
  type AvatarUser,
} from "./primitives";

export { tokens, type TokenName } from "./tokens";

export { api, ApiError, API_BASE } from "./api";

export {
  useCurrentUser,
  usePermissions,
  useCapabilities,
  useHasPlugin,
  useItemsQuery,
  useItemQuery,
  useProjectsQuery,
  useApiQueryClient,
} from "./hooks";

export type {
  Me,
  UserRef,
  Project,
  StateRef,
  Item,
  Permissions,
  PermissionValue,
  Capability,
  PluginRemote,
  CapabilitiesManifest,
} from "./types";

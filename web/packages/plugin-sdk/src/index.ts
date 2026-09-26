/**
 * @radd/plugin-sdk — the public frontend surface for Radd plugins (docs/plugin-platform.md §9).
 * The platform API imported by plugin UI. Owner-defined public packages may supply data/type
 * contracts; feature implementations remain behind contributions. Shared as a singleton so the slot registry,
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
  ButtonVariant,
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

export {
  provideHostComponents,
  DirectoryPager, ListSearchInput,
  SettingsPage, SelectField, Callout, CalloutKind, QueryError,
  CodeEditor,
  TokenList,
  type HostComponents,
  type CodeEditorProps,
  type TokenListProps,
  type SchemaFormProps,
} from "./host";

export { api, ApiError, API_BASE, provideApiTransport, errorMessage, type Paged, type RequestOptions as ApiRequestOptions } from "./api";

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

export { registerDataSource, unregisterDataSources, usePluginData, invalidatePluginData, type DataSource, type DataContracts, type PersonIndicator, type TimesheetAnnotation, type StatusIndicator } from "./data";

export * from "./dates";

export { DirectorySelect, PagedDirectorySelect, DIRECTORY_SELECT_SLOT, type DirectoryChoice, type DirectorySelectProps, type DirectoryQuery } from "./directory";

export { SchemaForm } from "./schema-form";
export { defaultsFromSchema } from "./schema-defaults";

export { OptionChoices, OptionSelect, OptionTextField, OptionNameValues, optionContribution, OPTION_CONTROL_SLOT, type DirectoryOption, type OptionSource, type OptionChoicesProps, type OptionSelectProps, type OptionTextFieldProps, type OptionNameValuesProps } from "./options";

export { Switch } from "./switch";
export { usePagedDirectory, type PagedDirectoryQuery } from "./paged-directory";

export { TokenMultiSelect, type TokenOption, type TokenMultiSelectProps } from "./token-multi-select";
export { ErrorText, type ErrorTextProps } from "./error-text";

export { registerQuerySource, unregisterQuerySources, useContributedQuery, type QuerySource } from "./query-sources";

export { ScheduleKind, defaultSchedule, isScheduleValid, type ScheduleKindValue, type ScheduleConfig, type SchedulePreview } from "./schedule";
export { ScheduleEditor, type ScheduleEditorProps } from "./schedule-editor";

export { ChangeList, ChangeLine, changeLabel, humanize, formatChangeValue } from "./ChangeLines";
export type { HistoryChange } from "./changes";
export { CollapsibleCard } from "./CollapsibleCard";
export { Pager } from "./Pager";
export { DateField } from "./DateField";
export { Table, THead, TBody, Th, Td } from "./Table";
export { TableSkeleton } from "./TableSkeleton";

export { IconButton } from "./IconButton";

export { ConfirmDialog, useConfirm, type ConfirmOptions } from "./ConfirmDialog";

export { copyText } from "./clipboard";

export { useListFilter } from "./list-filter";
export { useDebounced } from "./debounced";

export { registerCommandSource, unregisterCommandSources, useContributedCommands, invalidatePluginCommands, type Command, type CommandContext, type CommandSource, type ContributedCommand } from "./commands";
export { positionedErrorOf, type PositionedError } from "./positioned-error";

export { invalidateEntities } from "./cache";

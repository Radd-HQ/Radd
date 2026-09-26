/**
 * @radd/plugin-sdk — the public frontend surface for Radd plugins (docs/plugin-platform.md §9).
 * The platform API imported by plugin UI. Owner-defined public packages may supply data/type
 * contracts; feature implementations remain behind contributions. Shared as a singleton so the slot registry,
 * primitives, hooks and theme are ONE instance across the host and every remote.
 */

export { UI_API_VERSION, isUiApiCompatible } from "./version";
export { setRemotesLoading, useRemotesLoading } from "./remote-loading";

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
  ScopedSettings,
  RoleGrants,
  toast,
  ToastKind,
  type ScopedSettingsProps,
  type RoleGrantsProps,
  type RoleGrantSubject,
  type ToastKindValue,
  type HostComponents,
  type CodeEditorProps,
  type TokenListProps,
  type SchemaFormProps,
} from "./host";

export { api, ApiError, API_BASE, provideApiTransport, errorMessage, type Paged, type RequestOptions as ApiRequestOptions } from "./api";

export {
  useCurrentUser,
  useIsAuthenticated,
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
  ProjectSettingsPageProps,
  StateRef,
  Item,
  Permissions,
  PermissionValue,
  Capability,
  PluginRemote,
  CapabilitiesManifest,
  WidgetTypeOption,
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

export { registerQuerySource, unregisterQuerySources, useContributedQuery, useContributedQueries, type QuerySource, type ContributedQueryRequest, type ContributedQueryResult } from "./query-sources";
export { itemAttribute, useItemAttributes, ItemAttributeCell, ItemAttributeSurface, ITEM_ATTRIBUTE_BATCH_MAX, type ItemAttribute, type ItemAttributeSpec, type ItemAttributeCellProps, type ItemAttributeBatchArgs, type ItemAttributeSurfaceValue } from "./item-attributes";

export { ScheduleKind, defaultSchedule, isScheduleValid, type ScheduleKindValue, type ScheduleConfig, type SchedulePreview } from "./schedule";
export { ScheduleEditor, type ScheduleEditorProps } from "./schedule-editor";

export { ChangeList, ChangeLine, changeLabel, humanize, formatChangeValue } from "./ChangeLines";
export type { HistoryChange } from "./changes";
export { CollapsibleCard } from "./CollapsibleCard";
export { Pager } from "./Pager";
export { DateField } from "./DateField";
export { Table, THead, TBody, Th, Td } from "./Table";
export { useKeyedRows } from "./keyed-rows";
export { TableSkeleton } from "./TableSkeleton";

export { IconButton } from "./IconButton";

export { ConfirmDialog, useConfirm, type ConfirmOptions } from "./ConfirmDialog";

export { copyText } from "./clipboard";

export { useListFilter } from "./list-filter";
export { useDebounced } from "./debounced";

export { registerCommandSource, unregisterCommandSources, useContributedCommands, invalidatePluginCommands, type Command, type CommandContext, type CommandSource, type ContributedCommand } from "./commands";
export { positionedErrorOf, type PositionedError } from "./positioned-error";

export { invalidateEntities } from "./cache";

export { SlqField, PageQueryFilter, ViewSelect, SharingDialog, ReportWidget, ItemKeyLink, ItemPeek, MissingPluginType } from "./host-surfaces";
export type { SlqFieldProps, PageQueryFilterProps, ViewSelectProps, SharingDialogProps, SharedResourceSave, ReportWidgetProps, ItemKeyLinkProps, ItemPeekProps, MissingPluginTypeProps } from "./host-registry";
export { ChartHeightContext } from "./chart-height";
// Documents (RADD-1392): the `radd:*` block registry and its contexts are shared state, the text
// helpers are shared by the host editor and plugin surfaces, and the editor, viewer, markdown, AI
// and live-editing surfaces are the host's, bridged.
export {
  MarkdownSourceContext, PageExtensionCtx, usePageExtensionContext, registerPageExtension, pageExtensions,
  lookupPageExtension, extensionNameOf, extensionNameOfInfo, splitExtensionBlocks, parseExtensionParams,
  ExtensionCard, UnknownExtension, ExtensionError,
  type PageExtension, type PageExtensionContext, type BodySegment,
} from "./page-extensions";
export { headingAnchorId, headingsOf, type OutlineHeading } from "./markdown-outline";
export { ANCHOR_CONTEXT_CHARS, makeAnchor, locateAnchor, orderByAnchor, type TextAnchor, type AnchorLocation } from "./anchoring";
export {
  registerTextProjection, textNodesOf, renderedText, rangeForOffsets, revealTextOffset, offsetsForSelection,
  scrollRangeIntoView,
} from "./dom-text";
export {
  RichEditor, RichViewer, Markdown, AiReadMenu, AiResultsPane, EditingNow, useLiveSession, LiveRole,
  type RichEditorProps, type RichViewerProps, type MarkdownProps, type AiReadMenuProps, type AiResultsPaneProps,
  type EditingNowProps, type AiRun, type TaskToggle, type InlineAnchorRef, type LiveRoom, type LiveRoleValue,
  type LivePerson, type LiveSession, type LiveSessionOptions,
} from "./host-document";
export {
  CommentReplies, CommentHistory, CopyCommentLink, ThreadBadge, ThreadFilter, ResolveThreadButton, CommentSection,
  useCommentFeed, useLinkedComment, useLandOnComment, useThreadExpansion, commentHref, repliesLabel, threadRuleClass,
  sendTaskToggle,
  type CommentRow, type CommentAnchor, type CommentSectionValue, type CommentFeed, type CommentFeedOptions,
  type CommentLocation, type ThreadExpansion, type CommentRepliesProps, type CommentHistoryProps,
} from "./host-comments";
export {
  DropdownMenu, Popover, AccessGrantsEditor, ScopedAccess, StateCategoryDot, SidebarSection, SidebarLink, useDismiss,
  type MenuItem, type MenuTriggerProps, type DropdownMenuProps, type PopoverProps, type AccessGrantsEditorProps,
  type ScopedAccessProps, type SidebarSectionProps, type SidebarLinkProps,
} from "./host-kit";

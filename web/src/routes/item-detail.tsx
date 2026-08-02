import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Slot, SlotId } from "@radd/plugin-sdk";
import { Archive, ArchiveRestore, Flag, Pencil, Star, Trash2, SlidersHorizontal } from "lucide-react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { customFieldErrors, deniedCustomFieldKeys, errorMessage } from "../lib/api";
import { RoutePath } from "../lib/constants";
import { useArchiveItem, useDeleteItem, useToggleStarOnItem, useUpdateItem } from "../lib/item-mutations";
import { useItemWritability, usePermissions, usePointsEnabled } from "../lib/hooks";
import {
  fieldsQuery,
  itemPagesQuery,
  itemWebLinksQuery,
  projectTimeloggingQuery,
  statesQuery,
} from "../lib/queries";
import {
  AttachmentParentType,
  ItemKind,
  Permission,
  type CustomFieldValue,
  type CustomFields,
  type Item,
  type Project,
} from "../lib/types";
import { LazyRichViewer as RichViewer } from "../components/editor/LazyRichViewer";
import type { AiRun } from "../components/editor/ai";
import { AiReadMenu } from "../components/editor/AiReadMenu";
import { Button } from "../components/Button";
import { useIssueQuickActions } from "../components/items/quick-actions";
import { recordRecentItem, removeRecentItem } from "../lib/recent";
import { ChildCount, KindBadge, ParentTag } from "../components/items/ItemBadges";
import { WatchButton } from "../components/items/WatchButton";
import { AttachmentsSection } from "../components/items/AttachmentsSection";
import { LazyRichEditor as RichEditor } from "../components/editor/LazyRichEditor";
import { useAttachmentUploader } from "../lib/useAttachmentUploader";
import { attachmentUrl } from "../lib/constants";
import { ActivityPanel } from "../components/items/ActivityPanel";
import { useRollupBatch } from "../components/items/RollupBar";
import { ChildrenSection } from "../components/items/ChildrenSection";
import { CollapsibleCard } from "../components/CollapsibleCard";
import { DependenciesSection, dependencyLinkCount } from "../components/items/DependenciesSection";
import { MentionsSection } from "../components/items/MentionsSection";
import { SidePanel } from "../components/SidePanel";
import { IssueProperties } from "../components/items/IssueProperties";
import { AiSection } from "../components/items/AiSection";
import { AiResultsPanel } from "../components/items/AiResultsPanel";
import { AiResultsContext, type AiResultRequest } from "../components/items/ai-results";
import { RelatedLinksSection } from "../components/items/RelatedLinksSection";
import { ItemPagesSection } from "../components/items/ItemPagesSection";

/** Debounce for text-ish custom-field edits before PATCHing. */
const CUSTOM_FIELD_SAVE_DELAY_MS = 600;

interface ItemDetailBodyProps {
  project: Project;
  item: Item;
}

/**
 * The shared item-detail editor. Rendered by the canonical issue page
 * (`/issues/$itemKey`, spec 21) and the side panel (spec 25).
 *
 * Layout (issue-view redesign): a reading column — summary, description,
 * dependencies, comments — beside a right-hand properties rail
 * (`IssueProperties`) holding every metadata field. A container query splits
 * the two once there's room (the full page); the narrow side panel stacks them,
 * properties first. This keeps the content the user reads and writes clear of
 * the field clutter that previously sat between the description and comments.
 */
export function ItemDetailBody({ project, item }: ItemDetailBodyProps) {
  // Recently-viewed trail for the My Work dashboard (spec 37) — both the full
  // page and the peek panel render through here.
  useEffect(() => recordRecentItem(item.key, item.title), [item.key, item.title]);
  const states = useQuery(statesQuery(project.id));
  const fields = useQuery(fieldsQuery());
  const timelogging = useQuery(projectTimeloggingQuery(project.id));
  // Counts for the collapsed Related-links card (web links + linked docs) —
  // the same cache entries the sections read, so this costs nothing extra.
  const webLinks = useQuery(itemWebLinksQuery(item.id));
  const itemPages = useQuery(itemPagesQuery(item.id));
  const updateItem = useUpdateItem(project.id);
  const quickActions = useIssueQuickActions(item, project.id);
  const toggleStar = useToggleStarOnItem();
  const perms = usePermissions();
  const canEditItem = perms.project(project, Permission.itemUpdate);
  const canManageProject = perms.project(project, Permission.projectManage);
  // Per-field writability (spec 92): title/description/flag are grant-restrictable builtins, so gate
  // each on its own resolved verdict — disable up front rather than 403 on save.
  const writ = useItemWritability(project);
  const canEditTitle = writ.fieldWritable("title");
  const canEditDescription = writ.fieldWritable("description");
  const archiveItem = useArchiveItem();
  const deleteItem = useDeleteItem();
  // Pasted/inserted description images go through the storage-choice seam
  // (spec 102); a dismissed prompt rejects, so the editor insert aborts.
  const uploadFiles = useAttachmentUploader({
    entityType: AttachmentParentType.item,
    entityId: item.id,
  });
  const navigate = useNavigate();
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const archived = Boolean(item.archived_at);
  // Epic progress (spec 76): the rollup batch for just this item. Fetched for
  // ANY item that has children, not only epics — the subtask checklist shows
  // "2/5 done" and without the rollup it could only ever say 0 (RADD-660).
  const isEpic = item.kind === ItemKind.epic;
  const hasChildren = (item.child_count ?? 0) > 0;
  const rollupByItem = useRollupBatch([item.id], isEpic || hasChildren);
  const pointsEnabled = usePointsEnabled(project.id);

  // Local drafts (seeded per item via the `key` on ItemDetailBody).
  const [title, setTitle] = useState(item.title);
  const [description, setDescription] = useState(item.description);
  const [editingDescription, setEditingDescription] = useState(false);
  // A read-mode AI transform pending for the description edit session about to
  // open — handed to the editor as its initial whole-document run.
  const [pendingAiRun, setPendingAiRun] = useState<AiRun | null>(null);
  // AI results pane (the dead-space fix): summarize / find-similar answers
  // open BESIDE the reading column instead of a popover or the w-72 rail.
  // runId bumps per request so re-running the same summarize re-fires.
  const [aiResults, setAiResults] = useState<{ request: AiResultRequest; runId: number } | null>(
    null,
  );
  const openAiResults = useCallback((request: AiResultRequest) => {
    setAiResults((current) => ({ request, runId: (current?.runId ?? 0) + 1 }));
  }, []);
  const [customFields, setCustomFields] = useState<CustomFields>(item.custom_fields);
  const pendingCustom = useRef<CustomFields>({});
  const saveTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => () => clearTimeout(saveTimer.current), []);

  const patch = (body: Parameters<typeof updateItem.mutate>[0]["patch"]) => {
    updateItem.mutate({ itemId: item.id, patch: body });
  };

  const saveTitle = () => {
    const trimmed = title.trim();
    if (trimmed && trimmed !== item.title) patch({ title: trimmed });
    else setTitle(item.title);
  };

  const saveDescription = () => {
    if (description !== item.description) patch({ description });
    setEditingDescription(false);
    setPendingAiRun(null);
  };

  const onCustomFieldChange = (fieldKey: string, value: CustomFieldValue) => {
    setCustomFields((previous) => ({ ...previous, [fieldKey]: value }));
    pendingCustom.current[fieldKey] = value;
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      const changes = pendingCustom.current;
      pendingCustom.current = {};
      // PATCH merges custom_fields server-side, so only changed keys go out.
      patch({ custom_fields: changes });
    }, CUSTOM_FIELD_SAVE_DELAY_MS);
  };

  // Registry 422s map per key; a field-grant 403 (spec 07) names the denied
  // keys in its detail — surface both inline on the matching controls. Grants
  // aren't knowable client-side up front, so inputs stay enabled until then.
  const fieldErrors = useMemo(() => {
    if (!updateItem.isError) return {};
    const errors = customFieldErrors(updateItem.error);
    for (const key of deniedCustomFieldKeys(updateItem.error)) {
      errors[key] = "You don't have write access to this field.";
    }
    return errors;
  }, [updateItem.isError, updateItem.error]);

  return (
    <AiResultsContext.Provider value={openAiResults}>
      <header className="flex items-center gap-2 border-b border-subtle px-5 py-3">
        <KindBadge kind={item.kind} withLabel />
        <span className="font-mono text-xs text-fg-muted">{item.key}</span>
        {item.kind === ItemKind.epic && <ChildCount count={item.child_count ?? 0} />}
        {item.parent && (
          <Link
            to={RoutePath.issue}
            params={{ itemKey: item.parent.key }}
            aria-label={`Open parent ${item.parent.key}`}
          >
            <ParentTag parent={item.parent} />
          </Link>
        )}
        <div className="ml-auto">
          <WatchButton item={item} />
        </div>
        <button
          type="button"
          onClick={() => toggleStar.mutate({ itemId: item.id, star: !item.starred })}
          aria-pressed={Boolean(item.starred)}
          title={item.starred ? "Unstar" : "Star this issue"}
          className={
            "flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs cursor-pointer " +
            (item.starred
              ? "border-amber-400/50 bg-amber-400/10 text-amber-200"
              : "border-strong text-fg-secondary hover:text-fg hover:border-emphasis")
          }
        >
          <Star size={13} fill={item.starred ? "currentColor" : "none"} aria-hidden />
          {item.starred ? "Starred" : "Star"}
        </button>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => archiveItem.mutate({ itemId: item.id, archived: !archived })}
          title={archived ? "Unarchive" : "Archive — hidden from lists until restored"}
        >
          {archived ? <ArchiveRestore size={13} aria-hidden /> : <Archive size={13} aria-hidden />}
          {archived ? "Unarchive" : "Archive"}
        </Button>
        {(deleteItem.isError || archiveItem.isError) && (
          <span className="text-xs text-red-400">
            {errorMessage(deleteItem.isError ? deleteItem.error : archiveItem.error)}
          </span>
        )}
        {canManageProject &&
          (confirmingDelete ? (
            <span className="flex items-center gap-1.5">
              <Button
                variant="danger"
                size="sm"
                onClick={() =>
                  deleteItem.mutate(item.id, {
                    onSuccess: () => {
                      removeRecentItem(item.key);
                      void navigate({ to: RoutePath.home, search: {} });
                    },
                  })
                }
              >
                {deleteItem.isPending ? "Deleting…" : "Confirm delete"}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setConfirmingDelete(false)}>
                Keep
              </Button>
            </span>
          ) : (
            <Button
              variant="danger-ghost"
              size="sm"
              onClick={() => setConfirmingDelete(true)}
              title="Delete permanently (audit history remains)"
            >
              <Trash2 size={13} aria-hidden />
              Delete
            </Button>
          ))}
        <button
          type="button"
          disabled={!writ.fieldWritable("flagged")}
          onClick={() => patch({ flagged: !item.flagged })}
          aria-pressed={Boolean(item.flagged)}
          title={
            writ.fieldWritable("flagged")
              ? item.flagged
                ? "Remove flag"
                : "Flag this issue"
              : writ.reasonFor("flagged")
          }
          className={
            "flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs cursor-pointer " +
            "disabled:cursor-not-allowed disabled:opacity-70 disabled:hover:border-strong " +
            (item.flagged
              ? "border-amber-500/50 bg-amber-500/10 text-amber-300"
              : "border-strong text-fg-secondary hover:text-fg hover:border-emphasis")
          }
        >
          <Flag size={13} fill={item.flagged ? "currentColor" : "none"} aria-hidden />
          {item.flagged ? "Flagged" : "Flag"}
        </button>
        {/* Plugin-contributed header actions (spec 94): a plugin adds a button next to the title
            by registering an `issue.title.action` slot — no edit here. */}
        <Slot id={SlotId.issueTitleAction} item={item} project={project} />
      </header>

      {/* Named container (`/page`): elements nested inside SMALLER containers
          (the fields card runs its own @container) can still query the page's
          width — the SidePanel collapse toggle depends on it. */}
      <div className="@container/page min-h-0 flex-1 overflow-y-auto bg-base">
        {/* min-h-full: the column fills the fold so the conversation card owns
            the page bottom instead of leaving a dead band under it. */}
        <div className="flex min-h-full flex-col p-4">
          {/* Banner + title stay ABOVE the split (the peek must show the title
              before the properties stack), so they can't live inside the
              centered reading column — instead they mirror the rail's width
              (w-72 + ml-3 + gap-3 = 19.5rem) and center to the same measure,
              keeping the title's left edge flush with the description card.
              (If the rail is collapsed the mirror is a little wide — cosmetic.) */}
          <div className="@3xl:mr-[19.5rem]">
            <div className="mx-auto w-full max-w-[64rem]">
              {archived && (
                <p className="mb-3 flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-300">
                  <Archive size={13} aria-hidden />
                  This issue is archived — it's hidden from boards and lists until restored.
                </p>
              )}
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                onBlur={saveTitle}
                onKeyDown={(event) => {
                  if (event.key === "Enter") (event.target as HTMLInputElement).blur();
                }}
                aria-label="Title"
                maxLength={500}
                disabled={!canEditTitle}
                title={canEditTitle ? undefined : writ.reasonFor("title")}
                className="w-full rounded-md border border-transparent bg-transparent px-1.5 py-1 text-lg font-semibold text-heading hover:border-subtle focus:border-strong focus:outline-2 focus:outline-offset-1 focus:outline-focus disabled:cursor-not-allowed disabled:opacity-70 disabled:hover:border-transparent"
              />
            </div>
          </div>

          <div className="mt-3 flex flex-1 flex-col gap-3 @3xl:flex-row">
          {/* Reading column: description, dependencies, links, then the
              conversation — ALWAYS stacked (discussion belongs under the
              document), capped at a prose measure and centered in the space
              left of the edge-anchored properties rail. When the AI results
              pane is open it sits BESIDE the stack (in what was dead space),
              shifting the reading measure left; below @4xl it stacks on top. */}
          <div className="order-2 flex min-w-0 flex-1 flex-col items-center gap-3 @4xl:flex-row @4xl:items-start @4xl:justify-center">
          {aiResults && (
            <AiResultsPanel
              request={aiResults.request}
              runId={aiResults.runId}
              onClose={() => setAiResults(null)}
              className="order-first w-full max-w-[64rem] @4xl:sticky @4xl:top-0 @4xl:order-2 @4xl:max-h-[calc(100vh-12rem)] @4xl:w-96 @4xl:shrink-0"
            />
          )}
          <div className="flex w-full min-w-0 max-w-[64rem] flex-col gap-3">
            {/* Description + attachments are one card: they are the same act of
                reading, and splitting them would put a seam mid-thought. */}
            <section className="rounded-xl border border-subtle bg-surface p-4 shadow-lift">
            {editingDescription ? (
              <div className="flex flex-col gap-2">
                <RichEditor
                  value={description}
                  onChange={setDescription}
                  onUploadImage={async (file) => {
                    const [attachment] = await uploadFiles([file]);
                    return attachmentUrl(attachment.id);
                  }}
                  placeholder="Add a description… (toolbar above, or type markdown)"
                  autoFocus
                  quickActions={quickActions}
                  initialAiRun={pendingAiRun ?? undefined}
                  className="[&_.ProseMirror]:min-h-[12rem]"
                />
                <div className="flex gap-2">
                  <Button size="sm" onClick={saveDescription}>
                    Save
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setDescription(item.description);
                      setEditingDescription(false);
                      setPendingAiRun(null);
                    }}
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            ) : item.description ? (
              <div className="group/desc relative rounded-md border border-transparent px-1.5 py-1 hover:border-subtle">
                <RichViewer text={item.description} />
                <span className="absolute right-1 top-1 hidden items-center gap-1 group-hover/desc:flex">
                  {/* Read-mode AI (spec 103 follow-up): find-similar/summarize
                      for every reader; transforms only when writable. */}
                  <AiReadMenu
                    text={item.description}
                    similar={{ itemId: item.id }}
                    summarizeItemId={item.id}
                    onTransform={
                      canEditDescription
                        ? (run) => {
                            setPendingAiRun(run);
                            setEditingDescription(true);
                          }
                        : undefined
                    }
                    label="AI actions for the description"
                  />
                  {canEditDescription && (
                    <button
                      type="button"
                      onClick={() => {
                        setPendingAiRun(null);
                        setEditingDescription(true);
                      }}
                      aria-label="Edit description"
                      title="Edit description"
                      className="rounded p-1 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
                    >
                      <Pencil size={12} aria-hidden />
                    </button>
                  )}
                </span>
              </div>
            ) : canEditDescription ? (
              <button
                type="button"
                onClick={() => setEditingDescription(true)}
                className="rounded-md border border-transparent px-1.5 py-1 text-left text-[13px] text-fg-faint hover:border-subtle hover:text-fg-secondary cursor-pointer"
              >
                Add a description…
              </button>
            ) : (
              <p
                title={writ.reasonFor("description")}
                className="px-1.5 py-1 text-[13px] text-fg-faint"
              >
                No description.
              </p>
            )}

            {updateItem.isError && Object.keys(fieldErrors).length === 0 && (
              <p className="mt-1 text-xs text-red-400">
                Save failed: {errorMessage(updateItem.error)}
              </p>
            )}

            <AttachmentsSection item={item} canEdit={canEditItem} />
            </section>

            {/* Epic progress (spec 76) is now the HEADER of an expandable list
                (RADD-655): the bar answers "how much is left", and one click
                answers "which items" — previously that meant leaving the page
                and filtering a board by parent. Subtask children render as a
                checklist instead of rows (RADD-660). */}
            {item.kind !== ItemKind.subtask && (
              <ChildrenSection
                item={item}
                project={project}
                rollup={rollupByItem?.[item.id]}
                showPoints={pointsEnabled}
              />
            )}

            {/* Reference material, not first-glance info: collapsed cards with
                count chips — expanding is one click, the empty add-forms no
                longer occupy half the column (page AND peek). */}
            <CollapsibleCard title="Dependencies" count={dependencyLinkCount(item.links)}>
              <DependenciesSection project={project} item={item} />
            </CollapsibleCard>

            <MentionsSection item={item} />

            <CollapsibleCard
              title="Related links"
              count={(webLinks.data?.length ?? 0) + (itemPages.data?.length ?? 0)}
            >
              <RelatedLinksSection item={item} project={project} />
              {/* Pages pages linked to this issue (spec 43) — a block inside the
                  card, not its own section; absent when the docs module is. */}
              <ItemPagesSection item={item} />
            </CollapsibleCard>

            {/* The conversation card absorbs the leftover height (it stretches
                to the page bottom, so no dead band under it); the composer
                follows the thread and the card's tail is room for it to grow. */}
            <section className="flex flex-1 flex-col rounded-xl border border-subtle bg-surface p-4 shadow-lift">
              <ActivityPanel
                item={item}
                project={project}
                timeloggingEnabled={Boolean(timelogging.data?.enabled)}
              />
            </section>
          </div>
          </div>

          {/* Properties rail: every metadata field, out of the reading flow. */}
          {/* Collapsible only where it DOCKS: below @3xl the rail stacks above
              the reading column, where collapsing buys no width. */}
          <SidePanel
            panelKey="issue-rail"
            label="Fields"
            icon={SlidersHorizontal}
            sideAt="@3xl"
            frameless
            className="order-1 @3xl:order-2 @3xl:ml-3 @3xl:self-start"
            expandedClassName="flex flex-col gap-3 @3xl:w-72 @3xl:shrink-0"
          >
            {/* AI affordances (spec 46) — renders nothing while AI is disabled.
                Above the properties: summarize/find-similar orient the reader
                before the metadata wall, in the page rail AND the peek. */}
            <AiSection item={item} />
            <IssueProperties
              project={project}
              item={item}
              patch={patch}
              states={states.data}
              fields={fields.data ?? []}
              customFields={customFields}
              fieldErrors={fieldErrors}
              onCustomFieldChange={onCustomFieldChange}
              timeloggingEnabled={Boolean(timelogging.data?.enabled)}
            />
          </SidePanel>
          </div>
        </div>
      </div>
    </AiResultsContext.Provider>
  );
}

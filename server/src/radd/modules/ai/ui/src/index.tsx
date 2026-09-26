import {
  definePlugin,
  SlotId,
  type EditorSelectionActionProps,
  type EditorToolbarActionProps,
  type ItemDraftAssistProps,
  type ReadActionProps,
} from "@radd/plugin-sdk";
import { EmbeddingHealthCard } from "./EmbeddingHealthCard";
import { AiSelectionAction } from "./editor/SelectionAction";
import { AiToolbarAction } from "./editor/ToolbarAction";
import { abortAiRuns } from "./editor/transform";
import { AiDraftSimilar } from "./forms/DraftSimilar";
import { ClassifyInspector, GenerateInspector } from "./inspectors";
import { AiRailSection } from "./issue/RailSection";
import { EditorAiPreference } from "./profile/EditorAiPreference";
import { askPaletteMode } from "./palette/ask";
import { naturalLanguageMode } from "./query-bar/natural-language";
import { AiReadMenu } from "./read/ReadMenu";
import { AiSettingsPage } from "./settings/AiSettingsPage";

/** The `ai` plugin's UI remote: every AI surface is contributed here, so the host names no AI.
 *  `deactivate` stops any run in flight. */
export default definePlugin({
  contributions: [
    { id: "settings", slot: SlotId.settingsPage, match: "/settings/ai", render: () => <AiSettingsPage /> },
    { id: "embedding-health", slot: SlotId.settingsSection, match: "monitoring", order: 20, render: () => <EmbeddingHealthCard /> },
    // The editor: a toolbar button and Ask AI over a selection, both running a transform the
    // editor reviews (RADD-1395).
    { id: "editor-toolbar", slot: SlotId.editorToolbarAction, label: "Editor AI button",
      render: (props) => <AiToolbarAction {...(props as unknown as EditorToolbarActionProps)} /> },
    { id: "editor-selection", slot: SlotId.editorSelectionAction, label: "Ask AI on a selection",
      render: (props) => <AiSelectionAction {...(props as unknown as EditorSelectionActionProps)} /> },
    // Rendered content: descriptions, comments, pages.
    { id: "read-menu", slot: SlotId.contentReadAction, label: "AI actions on text",
      render: (props) => <AiReadMenu {...(props as unknown as ReadActionProps)} /> },
    // The issue page: Summarize / Find similar at the top of the rail, answering in the pane.
    { id: "issue-rail", slot: SlotId.issueRailTop, order: 10, label: "Issue AI card",
      render: (props) => <AiRailSection {...(props as unknown as { item: { id: string; title: string } })} /> },
    // The submission form: similar open issues beside the draft.
    { id: "draft-similar", slot: SlotId.itemDraftAssist, label: "Similar issues while filing",
      render: (props) => <AiDraftSimilar {...(props as unknown as ItemDraftAssistProps)} /> },
    // The command palette's Ask (search by meaning) and the query bar's natural language → SLQ.
    askPaletteMode,
    naturalLanguageMode,
    // Profile: the personal opt-out for the editor's AI menu.
    { id: "profile", slot: SlotId.profileSection, toggleable: false, render: () => <EditorAiPreference /> },
  ],
  activate(ctx) {
    ctx.registerSlot(SlotId.automationNodeInspector, {
      id: "ai-classify-inspector",
      match: "ai.classify",
      render: (props) => <ClassifyInspector {...(props as unknown as InspectorProps)} />,
    });
    ctx.registerSlot(SlotId.automationNodeInspector, {
      id: "ai-generate-inspector",
      match: "ai.generate",
      render: (props) => <GenerateInspector {...(props as unknown as InspectorProps)} />,
    });
  },
  deactivate() {
    abortAiRuns();
  },
});

export interface InspectorProps {
  node: { type: string; params: Record<string, unknown> };
  params: Record<string, unknown>;
  onChange: (params: Record<string, unknown>) => void;
  schema?: Record<string, unknown>;
}

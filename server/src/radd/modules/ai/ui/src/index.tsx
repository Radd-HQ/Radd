import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { EmbeddingHealthCard } from "./EmbeddingHealthCard";
import { ClassifyInspector, GenerateInspector } from "./inspectors";
import { AiSettingsPage } from "./settings/AiSettingsPage";

/**
 * The `ai` plugin's UI remote (RADD-1325). It contributes the inspector forms for
 * its own automation nodes through `automation.node.inspector`, so the host's
 * automation editor carries no AI node type. `ai.validate` needs no bespoke form:
 * the host renders it from its served schema. Settings → AI is its page too
 * (RADD-1379); the nav entry is declared on the backend manifest, so disabling the
 * plugin withdraws both.
 */
export default definePlugin({
  contributions: [
    { id: "settings", slot: SlotId.settingsPage, match: "/settings/ai", render: () => <AiSettingsPage /> },
    { id: "embedding-health", slot: SlotId.settingsSection, match: "monitoring", order: 20, render: () => <EmbeddingHealthCard /> },
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
});

export interface InspectorProps {
  node: { type: string; params: Record<string, unknown> };
  params: Record<string, unknown>;
  onChange: (params: Record<string, unknown>) => void;
  schema?: Record<string, unknown>;
}

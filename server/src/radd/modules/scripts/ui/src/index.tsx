import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { ScriptsSettingsPage } from "./SettingsPage";
import { ScriptInspector } from "./ScriptInspector";

/**
 * The `scripts` plugin's UI remote (RADD-1325): the inspector for its two
 * automation nodes, contributed through `automation.node.inspector`. The Python
 * editor is the HOST's CodeMirror, reached through the SDK's `CodeEditor`, so the
 * remote ships no editor of its own.
 */
export default definePlugin({
  contributions: [{ id: "settings", slot: SlotId.settingsPage, match: "/settings/scripts", render: () => <ScriptsSettingsPage /> }],
  activate(ctx) {
    for (const type of ["script.run", "script.decide"]) {
      ctx.registerSlot(SlotId.automationNodeInspector, {
        id: `${type}-inspector`,
        match: type,
        render: (props) => {
          const { params, onChange } = props as {
            params: Record<string, unknown>;
            onChange: (params: Record<string, unknown>) => void;
          };
          return <ScriptInspector params={params} onChange={onChange} decide={type === "script.decide"} />;
        },
      });
    }
  },
});

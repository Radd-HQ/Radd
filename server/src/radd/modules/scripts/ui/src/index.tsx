import { definePlugin, SlotId } from "@radd/plugin-sdk";
import { ScriptsSettingsPage } from "./SettingsPage";
import { ScriptInspector } from "./ScriptInspector";

/** scripts: Settings → Scripts and the script-node inspector (the Python editor is the host's CodeEditor). */
export default definePlugin({
  contributions: [
    { id: "settings", slot: SlotId.settingsPage, match: "/settings/scripts", render: () => <ScriptsSettingsPage /> },
    ...["script.run", "script.decide"].map((type) => ({
      id: `${type}-inspector`,
      slot: SlotId.automationNodeInspector,
      match: type,
      render: (props: Record<string, unknown>) => {
        const { params, onChange } = props as {
          params: Record<string, unknown>;
          onChange: (params: Record<string, unknown>) => void;
        };
        return <ScriptInspector params={params} onChange={onChange} decide={type === "script.decide"} />;
      },
    })),
  ],
});

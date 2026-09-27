/** A plugin's node in the inspector: the plugin's own `automation.node.inspector`, else a form from
 * its served `params_schema`. The editor never judges such a node incomplete — its rules are the
 * plugin's, so saving asks the server. */
import { SchemaForm, Slot, SlotId, type AutomationNodeInspectorProps } from "@radd/plugin-sdk";
import type { AutomationCatalog, AutomationNode } from "./types";

type CatalogNode = AutomationCatalog["nodes"][number];

interface ContributedNodeFieldsProps {
  node: AutomationNode;
  /** Its catalog entry; absent when the plugin that provides it is not loaded. */
  entry: CatalogNode | undefined;
  onChange: (params: Record<string, unknown>) => void;
  /** Say which plugin provides it when that plugin draws no form of its own. */
  showProvider?: boolean;
}

export function ContributedNodeFields({ node, entry, onChange, showProvider = false }: ContributedNodeFieldsProps) {
  const inspector: AutomationNodeInspectorProps = { node, params: node.params, onChange, schema: entry?.params_schema };
  const fallback = (
    <>
      {showProvider && (
        <p data-node-provider={entry?.plugin ?? ""} className="text-[11px] text-fg-muted">
          {entry
            ? `Provided by the ${entry.plugin} plugin.`
            : "Provided by a plugin that is not enabled here. Its settings are kept; saving asks the server whether it can run."}
        </p>
      )}
      {entry && <SchemaForm schema={entry.params_schema} params={node.params} onChange={onChange} />}
    </>
  );
  return (
    <div className="flex flex-col gap-2">
      {entry?.description && <p className="text-xs text-fg-secondary">{entry.description}</p>}
      <Slot id={SlotId.automationNodeInspector} match={node.type} {...inspector} fallback={fallback} />
    </div>
  );
}

import { Layers } from "lucide-react";
import { iconFor } from "../../lib/icons";

/** A plugin nav link's declared icon, resolved through the one icon registry (RADD-1390). A name
 *  the registry doesn't ship falls back to Layers, the icon every plugin link used to share. */
export function PluginNavIcon({ name, size }: { name: string; size: number }) {
  const Icon = iconFor(name) ?? Layers;
  return <Icon size={size} aria-hidden />;
}

import { useMemo } from "react";
import { FileSearch, Sparkles } from "lucide-react";
import { useReadingPane } from "@radd/plugin-sdk";
import type { AiResultRequest } from "../types";
import { AiResultsBody } from "./ResultsBody";

/**
 * Open an AI answer in the reading pane — beside the text, where there is room (the issue page, a
 * wiki page) — or null where the surface has none, so the caller answers in its own popover. The
 * pane's frame is the host's; the answer is this plugin's, and closes if the plugin is withdrawn.
 */
export function useOpenAiResults(): ((request: AiResultRequest) => void) | null {
  const open = useReadingPane();
  return useMemo(() => {
    if (!open) return null;
    return (request: AiResultRequest) => {
      const title = request.kind === "similar" ? "Similar issues" : "Summary";
      const Icon = request.kind === "similar" ? FileSearch : Sparkles;
      open({
        title,
        label: `AI results — ${title}`,
        icon: <Icon size={12} className="text-fg-muted" aria-hidden />,
        render: () => <AiResultsBody request={request} />,
      });
    };
  }, [open]);
}

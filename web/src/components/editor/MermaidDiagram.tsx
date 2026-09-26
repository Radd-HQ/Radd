import { useEffect, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { renderMermaid } from "./mermaid";
import { useAppearance } from "../../lib/theme";

/** A rendered mermaid diagram. `dangerouslySetInnerHTML` is safe here: mermaid runs with
 *  `securityLevel: "strict"`, which strips scripts and handlers from the SVG. */
export function MermaidDiagram({ source }: { source: string }) {
  const [svg, setSvg] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(true);
  // Re-render when the theme flips: mermaid bakes colours INTO the svg, so a
  // diagram drawn in dark stays dark on a white page until it is drawn again.
  const { theme } = useAppearance();

  useEffect(() => {
    let current = true;
    setPending(true);
    renderMermaid(source).then((result) => {
      if (!current) return;
      setSvg(result.svg);
      setError(result.error);
      setPending(false);
    });
    return () => {
      current = false;
    };
  }, [source, theme]);

  if (error) {
    return (
      <div className="my-2 rounded-lg border border-subtle bg-surface p-3">
        <p className="flex items-start gap-1.5 text-[13px] text-fg-secondary">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-fg-muted" aria-hidden />
          <span>
            This diagram could not be drawn.{" "}
            <span className="text-fg-muted">{error}</span>
          </span>
        </p>
      </div>
    );
  }

  if (pending && !svg) {
    return (
      <div className="my-2 rounded-lg border border-subtle bg-surface px-3 py-6 text-center text-[13px] text-fg-faint">
        Drawing…
      </div>
    );
  }

  return (
    <div
      className="radd-mermaid my-2 flex justify-center overflow-x-auto rounded-lg border border-subtle bg-surface p-3"
      data-mermaid
      // See the component docstring: mermaid runs with securityLevel "strict".
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}

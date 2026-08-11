/**
 * Mermaid diagrams from a ```` ```mermaid ```` fence.
 *
 * The fence, not a `radd:mermaid` extension, deliberately: ```` ```mermaid ```` is
 * what GitHub, GitLab, Obsidian and Notion all render, so a page body written
 * here stays a diagram everywhere else it is pasted. An extension would make it
 * ours and nobody else's.
 *
 * **Loaded on demand.** Mermaid is megabytes; importing it at module scope would
 * put all of it in the main bundle for every page that has no diagram at all.
 * The dynamic import means Vite splits it out and the network only pays for it
 * on a page that actually draws something.
 */

import { Theme, getTheme } from "../../lib/theme";

type MermaidApi = typeof import("mermaid")["default"];

let loading: Promise<MermaidApi> | null = null;
let configuredTheme: string | null = null;

/** The mermaid theme that matches Radd's. */
function themeName(): "dark" | "default" {
  return getTheme() === Theme.light ? "default" : "dark";
}

/**
 * A house token's COMPUTED value.
 *
 * Mermaid bakes colours into the SVG it returns, so it cannot be handed
 * `var(--color-surface)` — it computes derived shades from whatever it is given
 * and a var string yields nonsense. Resolving the token here keeps the palette
 * the single source of truth without hardcoding a hex that would then have to be
 * maintained in two places and in two themes.
 */
function token(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

async function api(): Promise<MermaidApi> {
  if (!loading) {
    loading = import("mermaid").then((module) => module.default);
  }
  const mermaid = await loading;
  const wanted = themeName();
  if (configuredTheme !== wanted) {
    mermaid.initialize({
      startOnLoad: false,
      theme: wanted,
      securityLevel: "strict",
      fontFamily: "var(--radd-code-font)",
      themeVariables: {
        // Mermaid's own default is a pale swatch that sits on the diagram like a
        // sticky note — fine on its white canvas, wrong on ours in either theme.
        edgeLabelBackground: token("--color-surface", "transparent"),
        lineColor: token("--color-fg-muted", "#888"),
        textColor: token("--color-fg", "#ddd"),
      },
      // Mermaid renders its own error graphic into the page when parsing fails,
      // which lands outside our component and cannot be styled or cleared. We
      // want the failure reported next to the source instead.
      suppressErrorRendering: true,
    });
    configuredTheme = wanted;
  }
  return mermaid;
}

let counter = 0;

export interface MermaidResult {
  svg: string;
  error: string;
}

/**
 * Render one diagram. Never throws — a diagram with a typo in it is the common
 * case while someone is writing one, and it must show the error beside the
 * source rather than blanking the page.
 */
export async function renderMermaid(source: string): Promise<MermaidResult> {
  const text = source.trim();
  if (!text) return { svg: "", error: "" };
  try {
    const mermaid = await api();
    // A fresh id per render: mermaid keys internal state by it, and reusing one
    // makes a second diagram on the same page inherit the first one's.
    counter += 1;
    const { svg } = await mermaid.render(`radd-mermaid-${counter}`, text);
    return { svg, error: "" };
  } catch (error) {
    const message =
      error instanceof Error ? error.message : String(error ?? "could not render");
    return { svg: "", error: message };
  }
}

/** Whether a fence's language means "draw this". */
export const isMermaid = (language: string): boolean =>
  language.trim().toLowerCase() === "mermaid";

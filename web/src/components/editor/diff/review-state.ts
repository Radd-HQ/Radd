import { diffPluginKey } from "@milkdown/kit/plugin/diff";
import { Plugin } from "@milkdown/kit/prose/state";
import { DecorationSet } from "@milkdown/kit/prose/view";
import { $prose } from "@milkdown/kit/utils";

import { countReviewUnits, raddDiffDecorationKey } from "./decoration-plugin";

/**
 * The pending review, published to React (RADD-762).
 *
 * The diff lives in ProseMirror state, so the chrome that offers Accept all /
 * Reject all had no way to know a review was open, how much was left in it, or
 * when it ended. A plugin view is the same seam `selection-state.ts` and
 * `toolbar-state.ts` already use for that: it runs on exactly the updates that
 * can change the answer, rather than being polled.
 *
 * `changes` counts the Accept/Reject pairs the decoration fork RENDERS, not the
 * changeset's chunks — those differ by an order of magnitude on a rewrite, and
 * the number worth showing someone is the number of decisions in front of them.
 */
export interface ReviewState {
  /** A diff review is open; the editor rejects document edits until it ends. */
  active: boolean;
  /** Accept/Reject pairs still on screen. */
  changes: number;
}

export const NO_REVIEW: ReviewState = { active: false, changes: 0 };

export const reviewStatePlugin = (onChange: (state: ReviewState) => void) =>
  $prose(
    () =>
      new Plugin({
        view: (view) => {
          let last = NO_REVIEW;
          const publish = () => {
            const diffState = diffPluginKey.getState(view.state);
            const next: ReviewState = diffState?.active
              ? {
                  active: true,
                  changes: countReviewUnits(
                    raddDiffDecorationKey.getState(view.state) ?? DecorationSet.empty,
                  ),
                }
              : NO_REVIEW;
            if (last.active === next.active && last.changes === next.changes) return;
            last = next;
            onChange(next);
          };
          publish();
          return {
            update: publish,
            // A destroyed editor has no review, and this runs on a mode switch
            // or an AI-gate recreate — where the component lives on and would
            // otherwise keep a review panel open over an editor that is gone.
            destroy: () => onChange(NO_REVIEW),
          };
        },
      }),
  );

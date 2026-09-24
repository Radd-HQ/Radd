import { useMemo } from "react";
import { usePermissions } from "./hooks";
import type { PageSpace, Project } from "./types";

/**
 * "May this actor do X?" — one question, one answer, one treatment (RADD-771).
 *
 * The seam was not missing before, it was PLURAL: `usePermissions().global` for
 * instance-scoped atoms, `.project(project, atom)` for project-scoped ones,
 * `useItemWritability` for item fields, and per-resource server checks for the
 * spec-92 access framework. A component author had to know which of four
 * mechanisms applied before they could ask the question, which is a large part
 * of why 56 of 98 mutating components asked nothing at all.
 *
 * Here the SCOPE is chosen by what you pass, not by which hook you import: hand
 * it a project and it resolves against that project's permissions, omit one and
 * it resolves globally. Getting the scope wrong is the failure this is built to
 * prevent — RADD-770 shipped a page-comment gate that read `page.write`, an atom
 * every active user held unconditionally, so the check was present, passed
 * review, and behaved exactly like no check at all.
 *
 * ## `props` is the point
 *
 * The returned `props` spread does three things at once, and the third is why
 * this is worth a hook rather than a boolean:
 *
 *   - `disabled` — the control is inert rather than a trap.
 *   - `title` — the reason, on hover. Spec 96's decided treatment: dimmed, a
 *     reason, no lock icon.
 *   - `data-needs` — the atom this control claims to require, in the DOM.
 *
 * That last one converts "did we gate everything?" from an opinion into a
 * measurement. `scripts/restricted-access-proof.mjs` reads every `[data-needs]`
 * on a page and asserts `enabled === actor-holds-the-atom`, so a control that
 * lies about its own requirement fails a run. Annotation is a side effect of
 * using the seam, which is the only way it stays true — a convention nobody has
 * to remember is the only convention that survives.
 */

export interface Gate {
  /** The actor may do this. */
  allowed: boolean;
  /** Why not, for a tooltip. Empty when allowed. */
  reason: string;
  /** Spread onto the button/input this gates. */
  props: {
    disabled: boolean;
    title: string | undefined;
    "data-needs": string;
    "data-needs-project": string | undefined;
    /** `any` when the question was asked across projects (`anyProject`) —
     *  without it the proof would judge a cross-project claim against the
     *  GLOBAL set and call a correct gate a liar (RADD-778). */
    "data-needs-scope": "any" | undefined;
  };
}

export interface CanOptions {
  /** Resolve against this project. Omit for a global-scope atom. */
  project?: Pick<Project, "id" | "permissions"> | null;
  /**
   * Resolve against this wiki SPACE (RADD-814) — the space leg of the scope
   * ladder. The RADD-810 class was space-scoped atoms asked as global
   * questions because this option did not exist.
   */
  space?: Pick<PageSpace, "id" | "permissions"> | null;
  /**
   * Resolve against ANY project the caller can see (RADD-788) — for surfaces
   * that span projects and so have no single one to check. Ignored when
   * `project` is given, which is the more specific question.
   */
  anyProject?: boolean;
  /** Human phrase for the tooltip: "You can't <verb>." Falls back to the atom. */
  verb?: string;
  /** An extra condition that must ALSO hold — an archived item, a closed cycle.
   *  Keeps "may I" and "does it make sense right now" in one answer rather than
   *  letting callers re-implement the disabled treatment beside the gate. */
  unless?: { when: boolean; reason: string };
}

export type CanFn = (permission: string, options?: CanOptions) => Gate;

export function useCan(): CanFn {
  const perms = usePermissions();

  return useMemo<CanFn>(
    () => (permission, options = {}) => {
      const { project, space, anyProject, verb, unless } = options;
      const held = project
        ? perms.project(project, permission as never)
        : space
          ? perms.space(space, permission as never)
          : anyProject
            ? perms.anyProject(permission as never)
            : perms.global(permission as never);
      const blocked = unless?.when === true;
      const allowed = held && !blocked;
      const reason = allowed
        ? ""
        : blocked
          ? unless.reason
          : verb
            ? `You don't have permission to ${verb}.`
            : `You don't have the ${permission} permission.`;
      return {
        allowed,
        reason,
        props: {
          disabled: !allowed,
          title: allowed ? undefined : reason,
          "data-needs": permission,
          "data-needs-project": project?.id,
          "data-needs-scope": !project && !space && anyProject ? "any" : undefined,
        },
      };
    },
    [perms],
  );
}

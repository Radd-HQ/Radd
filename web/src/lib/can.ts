import { useMemo } from "react";
import { usePermissions } from "./hooks";
import type { PageSpace } from "@radd-plugin-ui/pages/types";
import type { Project } from "@radd-plugin-ui/projects/types";

/**
 * "May this actor do X?" in one hook. The SCOPE is chosen by what you pass —
 * a project, a space, `anyProject`, or nothing for global — because asking in
 * the wrong scope is the bug this exists to prevent (RADD-770).
 *
 * Spread `props` onto the control: `disabled`, the reason as `title`, and
 * `data-needs`, which `web/scripts/restricted-access-proof.mjs` reads to
 * assert every gated control's state matches the atom it declares.
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
  };
}

interface CanOptions {
  /** Resolve against this project. Omit for a global-scope atom. */
  project?: Pick<Project, "id" | "permissions"> | null;
  /** Resolve against this wiki SPACE (RADD-814). */
  space?: Pick<PageSpace, "id" | "permissions"> | null;
  /** Resolve against ANY visible project (RADD-788), for cross-project surfaces; `project` wins. */
  anyProject?: boolean;
  /** Human phrase for the tooltip: "You can't <verb>." Falls back to the atom. */
  verb?: string;
  /** An extra condition that must ALSO hold (an archived item, a closed cycle), so "may I" and
   *  "does it make sense now" share one disabled treatment. */
  unless?: { when: boolean; reason: string };
}

type CanFn = (permission: string, options?: CanOptions) => Gate;

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
        },
      };
    },
    [perms],
  );
}

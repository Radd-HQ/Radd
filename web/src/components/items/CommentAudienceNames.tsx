import { useState } from "react";
import { Button, Modal } from "@radd/plugin-sdk";
import { TeamAudience } from "../teams/TeamAudience";
export const COMMENT_TEAM_PREVIEW_SIZE = 3;
export const COMMENT_AUDIENCE_COPY = {
  emptyText: "Visible to everyone on this project who can read internal notes.",
  hint: "Team members still need access to this issue and internal notes. Project managers with internal-note access can also read it.",
};

/** Common small audiences stay named inline; larger ones have a complete pageable view. */
export function CommentAudienceNames({ ids, names }: { ids: string[]; names: Map<string, string> }) {
  const [open, setOpen] = useState(false);
  return <>
    <span>{ids.slice(0, COMMENT_TEAM_PREVIEW_SIZE).map(id => names.get(id) ?? "Unavailable team").join(", ")}</span>
    {ids.length > COMMENT_TEAM_PREVIEW_SIZE && <Button size="sm" variant="ghost" className="ml-1" aria-haspopup="dialog" onClick={() => setOpen(true)}>+{ids.length - COMMENT_TEAM_PREVIEW_SIZE} more teams</Button>}
    {open && <Modal title="Internal note audience" onClose={() => setOpen(false)}><TeamAudience value={ids} {...COMMENT_AUDIENCE_COPY} /></Modal>}
  </>;
}

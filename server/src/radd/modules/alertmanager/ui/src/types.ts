/** One receiver (`/alertmanager/receivers`). The token is write-only: only
 * whether one is set comes back. */
export type AlertReceiver = {
  id: string;
  name: string;
  project_id: string | null;
  active: boolean;
  /** RADD-1370: an internal comment when the alert repeats and when it resolves. */
  comment_updates: boolean;
  /** RADD-1370: a label every issue it creates carries ("" = none). */
  label: string;
  /** RADD-1370: where a resolved alert's issue moves — a state of its project. */
  resolve_state_id: string | null;
  has_token: boolean;
  created_at: string;
};

export type ReceiverPatch = Partial<Pick<AlertReceiver,
  "name" | "project_id" | "active" | "comment_updates" | "label" | "resolve_state_id">> & { token?: string };

/** The slice of a workflow state this page needs (`GET /states?project_id=`). */
export type StateChoice = { id: string; name: string };

export const RECEIVERS_PATH = "/alertmanager/receivers";
export const receiverPath = (id: string) => `${RECEIVERS_PATH}/${encodeURIComponent(id)}`;
export const receiversKey = ["alertmanager", "receivers"] as const;

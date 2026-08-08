/** Intake forms, public submit path, requester portal, and mail contacts (specs 20/62/73). */
import type { FieldDisplayValue, FieldTypeValue } from "./fields";
import type { CustomFieldValue, CustomFields, ItemKindValue, PriorityValue } from "./items";
// ---------------------------------------------------------------------------
// Intake forms (spec 20 — /forms). Per-project public-shaped submission forms
// that create a work item from a title + exposed registry-field values.
// ---------------------------------------------------------------------------

/** One field a form exposes, referencing a registry field by key (with overrides). */
export interface FormField {
  field_key: string;
  label_override?: string | null;
  help?: string | null;
  required: boolean;
}

/** Values applied to the item a submission creates (names resolve at submit). */
export interface FormDefaults {
  kind?: ItemKindValue | null;
  /** RADD-801 — spec 51's issue TYPE (Bug/Feature), a different axis from
   *  `kind` (epic/issue/subtask). The form used to offer only the latter. */
  type_name?: string | null;
  state_name?: string | null;
  priority?: PriorityValue | null;
  labels: string[];
  assignee_email?: string | null;
  cycle_name?: string | null;
  release_version?: string | null;
  start_date?: string | null;
  target_date?: string | null;
  flagged?: boolean;
  estimate_points?: number | null;
}

/** GET /forms?project_id= (list) and GET /forms/{id} (render for submit). */
export interface Form {
  id: string;
  project_id: string;
  name: string;
  description: string;
  enabled: boolean;
  fields: FormField[];
  defaults: FormDefaults;
  title_prompt: string;
  /** The item-description area on the submit page (not the form's own blurb). */
  description_enabled: boolean;
  description_prompt: string;
  description_required: boolean;
  /** RADD-798 — offer the submitter a picker of their own teams. */
  team_picker_enabled: boolean;
  /** Spec 62: the tokened no-login submit path. The token is minted on first
   * enable and KEPT on disable (re-enabling restores the same link). */
  allow_public: boolean;
  /** Portal share grants (spec 73) — populated on the form.manage surfaces. */
  shares: FormShare[];
  created_at: string;
  updated_at: string;
}

/** One portal grant row (spec 73): exactly one of user_id/team_id, no levels. */
export interface FormShare {
  id: string;
  user_id: string | null;
  team_id: string | null;
  created_at: string;
}

/** One subject in the PUT /forms/{id}/sharing payload. */
export interface FormShareEntry {
  user_id?: string;
  team_id?: string;
}

/** PUT /forms/{id}/sharing — the FULL share list, replaced wholesale. */
export interface FormSharingUpdate {
  shares: FormShareEntry[];
}

export interface FormCreate {
  project_id: string;
  name: string;
  description?: string;
  enabled?: boolean;
  fields?: FormField[];
  defaults?: FormDefaults;
  title_prompt?: string;
  description_enabled?: boolean;
  description_prompt?: string;
  description_required?: boolean;
  team_picker_enabled?: boolean;
}

/** PATCH /forms/{id} — omitted keys untouched. */
export interface FormUpdate {
  name?: string;
  description?: string;
  enabled?: boolean;
  fields?: FormField[];
  defaults?: FormDefaults;
  title_prompt?: string;
  description_enabled?: boolean;
  description_prompt?: string;
  description_required?: boolean;
  team_picker_enabled?: boolean;
  /** Spec 62: toggle the public link (token minted server-side on first enable). */
  allow_public?: boolean;
}

/** POST /forms/{id}/submit — a title plus the exposed fields' values. */
export interface FormSubmit {
  title: string;
  description?: string;
  values: CustomFields;
  /** RADD-798 — share with one of MY teams. Only offered when the form enables
   *  the picker; the server re-checks membership either way. */
  team_id?: string | null;
  /** RADD-800 — staged attachments this submission is claiming. */
  attachment_ids?: string[];
}

// ---------------------------------------------------------------------------
// Public form path + mail contacts (spec 62)
// ---------------------------------------------------------------------------

/** One exposed field with its definition inlined (the registry needs a login). */
export interface PublicFormField {
  field_key: string;
  label: string;
  help: string | null;
  required: boolean;
  type: FieldTypeValue;
  options: string[] | null;
  display: FieldDisplayValue | null;
  default_value: CustomFieldValue;
}

/** The trimmed render payload (portal base shape — the anonymous tokened
    path went with RADD-828). */
export interface PublicForm {
  name: string;
  description: string;
  title_prompt: string;
  description_enabled: boolean;
  description_prompt: string;
  description_required: boolean;
  fields: PublicFormField[];
}

/** What an anonymous submitter learns back: the created issue key only. */
export interface PublicSubmitResult {
  key: string;
  title: string;
}

/**
 * One external person on an item's mail thread (RADD-980).
 *
 * `GET /items/{id}/mail-contacts` returns them all, primary first (empty list = none);
 * `GET /items/{id}/mail-contact` still returns the PRIMARY alone, 404 when there is none.
 */
export interface MailContact {
  email: string;
  name: string;
  is_primary: boolean;
}

// ---------------------------------------------------------------------------
// Requester portal (spec 73) — the intake-form directory for signed-in users.
// ---------------------------------------------------------------------------

/** The project chrome a portal visitor sees — id/key/name only. */
export interface PortalProjectRef {
  id: string;
  key: string;
  name: string;
}

/** One directory card: trimmed by design (no tokens, no field config). */
export interface PortalFormCard {
  id: string;
  name: string;
  description: string;
}

/** GET /portal/forms — eligible forms grouped by project. */
export interface PortalGroup {
  project: PortalProjectRef;
  forms: PortalFormCard[];
}

/** GET /portal/forms/{id} — the public trimming + form id and project ref. */
export interface PortalForm extends PublicForm {
  id: string;
  project: PortalProjectRef;
  /** The teams THIS submitter may share with (RADD-798). Empty when the form
   *  has no picker or the person belongs to no team — either way, no control. */
  teams: PortalTeamOption[];
}

/**
 * One request you filed, as the portal shows it (RADD-785).
 *
 * Deliberately narrow — no description, comments, assignee or fields. A
 * requester is scoped by their RELATIONSHIP to the row (`reporter_id`), not by
 * `item.read`, so this must not become a back door into an issue's contents.
 */
export interface PortalRequest {
  key: string;
  title: string;
  state: string;
  state_category: string;
  project: { id: string; key: string; name: string };
  /** RADD-797 — the status a requester needs. Each of these is inside the
   *  relationship boundary: a directory NAME, a version string, and counts
   *  derived from PUBLIC comments only. */
  assignee: string | null;
  release: string | null;
  /** RADD-798 — the team it was shared with; the key both surfaces group by. */
  team: string | null;
  team_id: string | null;
  comment_count: number;
  /** The last PUBLIC comment was not the reporter's — "someone answered you". */
  awaiting_requester: boolean;
  created_at: string;
  updated_at: string;
}

/** One public comment on a request (RADD-796). Internal notes never appear. */
export interface PortalRequestComment {
  id: string;
  author: string;
  author_is_me: boolean;
  body: string;
  created_at: string;
}

/** GET /portal/requests/{key} — the row plus what you opened it for. */
export interface PortalRequestDetail extends PortalRequest {
  description: string;
  comments: PortalRequestComment[];
}

/** A team the SUBMITTER belongs to — the only teams a form may offer. */
export interface PortalTeamOption {
  id: string;
  name: string;
}

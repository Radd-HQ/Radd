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
  state_name?: string | null;
  priority?: PriorityValue | null;
  labels: string[];
  assignee_email?: string | null;
  cycle_name?: string | null;
  release_version?: string | null;
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
  /** Spec 62: the tokened no-login submit path. The token is minted on first
   * enable and KEPT on disable (re-enabling restores the same link). */
  allow_public: boolean;
  public_token: string | null;
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
  /** Spec 62: toggle the public link (token minted server-side on first enable). */
  allow_public?: boolean;
}

/** POST /forms/{id}/submit — a title plus the exposed fields' values. */
export interface FormSubmit {
  title: string;
  description?: string;
  values: CustomFields;
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

/** GET /public/forms/{token} — the unauthenticated render payload. */
export interface PublicForm {
  name: string;
  description: string;
  title_prompt: string;
  description_enabled: boolean;
  description_prompt: string;
  description_required: boolean;
  fields: PublicFormField[];
}

/** POST /public/forms/{token} — submission plus who is asking. */
export interface PublicFormSubmit {
  title: string;
  description?: string;
  values: CustomFields;
  email: string;
  name?: string;
}

/** What an anonymous submitter learns back: the created issue key only. */
export interface PublicSubmitResult {
  key: string;
  title: string;
}

/** GET /items/{id}/mail-contact — the item's external requester (404 = none). */
export interface MailContact {
  email: string;
  name: string;
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
  created_at: string;
  updated_at: string;
}

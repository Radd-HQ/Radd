/** Labels. */
// ---------------------------------------------------------------------------
// Labels
// ---------------------------------------------------------------------------

export interface Label {
  id: string;
  name: string;
  color: string | null;
  created_at: string;
}

export interface LabelCreate {
  name: string;
  color?: string | null;
}

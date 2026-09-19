/** The scripts plugin (RADD-1269). */

export interface ScriptSummary {
  id: string;
  name: string;
  description: string;
  version: number;
  updated_at: string;
}

export interface Script extends ScriptSummary {
  body: string;
  updated_by_id: string | null;
  created_at: string;
}

export interface ScriptVersion {
  id: string;
  version: number;
  body: string;
  note: string;
  created_by_id: string | null;
  created_at: string;
}

export interface ScriptPackage {
  id: string;
  name: string;
  spec: string;
  resolved_version: string;
  status: "pending" | "installed" | "failed";
  log: string;
  created_at: string;
  installed_at: string | null;
}

export interface ScriptInterpreter {
  python_version: string;
  status: "missing" | "ready" | "failed";
  resolved: string;
  log: string;
  built_at: string | null;
  path: string;
  available: string[];
  sdk_source: string;
}

export interface ScriptRunOutcome {
  ok: boolean;
  result: unknown;
  stdout: string;
  stderr: string;
  error: string;
  duration_ms: number;
}

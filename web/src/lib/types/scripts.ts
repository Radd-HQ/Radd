/** The scripts plugin (RADD-1269). */

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
  /** Where packages come from (RADD-1277): wheelhouses first, then the index. */
  wheelhouses: string[];
  operator_wheelhouse: string;
  /** "" = PyPI; a password in the URL arrives masked. */
  index_url: string;
  offline: boolean;
}

export interface ScriptInterpreterSettings {
  index_url: string;
  offline: boolean;
}

export interface ScriptRunOutcome {
  ok: boolean;
  result: unknown;
  stdout: string;
  stderr: string;
  error: string;
  duration_ms: number;
}

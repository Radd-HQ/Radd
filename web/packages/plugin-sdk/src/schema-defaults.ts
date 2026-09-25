/** Generic JSON-schema starting values, not a schema validator or a feature catalog. */
export interface SchemaProperty {
  type?: string;
  title?: string;
  description?: string;
  enum?: unknown[];
  default?: unknown;
  properties?: Record<string, SchemaProperty>;
  required?: string[];
  maxLength?: number;
  minimum?: number;
  maximum?: number;
}

export function defaultsFromSchema(schema: Record<string, unknown>): Record<string, unknown> {
  const properties = (schema.properties ?? {}) as Record<string, SchemaProperty>;
  const required = new Set((schema.required as string[]) ?? []);
  const entries: [string, unknown][] = [];
  for (const [key, property] of Object.entries(properties)) {
    let value: unknown;
    if (property.default !== undefined) value = structuredClone(property.default);
    else if (property.enum?.length && required.has(key)) value = structuredClone(property.enum[0]);
    else if (property.type === "array") value = [];
    else if (property.type === "object") value = defaultsFromSchema(property as Record<string, unknown>);
    else if (property.type === "string") value = "";
    else if (property.type === "number" || property.type === "integer") value = 0;
    else if (property.type === "boolean") value = false;
    else continue;
    entries.push([key, value]);
  }
  const rootDefault = schema.default && typeof schema.default === "object" && !Array.isArray(schema.default)
    ? structuredClone(schema.default) : {};
  return { ...Object.fromEntries(entries), ...rootDefault };
}

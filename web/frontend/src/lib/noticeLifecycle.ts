import type { JsonValue } from "./types";

export interface PreSpecLifecycleView {
  pre_spec_no: string | null;
  bid_ntice_no_list: string | null;
  changed_at: string | null;
  change_reason: string | null;
}

export interface ProcurementClassView {
  code: string | null;
  detail: string | null;
}

function objectValue(value: JsonValue): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

/** Opaque JSON is narrowed only at the documented keys; no lifecycle state is inferred. */
function optionalString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed && trimmed.toLowerCase() !== "unknown" ? trimmed : null;
}

export function readPreSpecLifecycle(value: JsonValue): PreSpecLifecycleView {
  const lifecycle = objectValue(value);
  return {
    pre_spec_no: optionalString(lifecycle?.pre_spec_no),
    bid_ntice_no_list: optionalString(lifecycle?.bid_ntice_no_list),
    changed_at: optionalString(lifecycle?.changed_at),
    change_reason: optionalString(lifecycle?.change_reason),
  };
}

export function readProcurementClass(value: JsonValue): ProcurementClassView {
  const procurementClass = objectValue(value);
  return {
    code: optionalString(procurementClass?.code),
    detail: optionalString(procurementClass?.detail),
  };
}

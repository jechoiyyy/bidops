import type { Mark } from "../common/Marks";
import { gateResultLabel } from "../../lib/glossary";
import type { C2QualityGateResultStatus, QualityGateResultStatus } from "../../lib/types";

export function gateResultMark(status: QualityGateResultStatus | C2QualityGateResultStatus): Mark {
  return {
    label: gateResultLabel(status),
    tone: status === "통과" ? "success" : status === "미달" ? "error" : "neutral",
  };
}

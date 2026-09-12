import type { BundleView } from "../components/deep-review/types";
import type { PreSpecAutoPreparationStatus } from "./types";

/** 조치·폴링이 필요한 묶음은 자동 준비 상태보다 먼저 펼친다. */
export function documentPanelDefaultOpen(
  bundle: BundleView | null,
  autoStatus: PreSpecAutoPreparationStatus | null,
): boolean {
  if (bundle === null || (bundle.status !== "ready" && bundle.status !== "superseded")) return true;
  return autoStatus === "deep_review_ready_for_click"
    || autoStatus === "blocked"
    || autoStatus === "waiting_attachments"
    || autoStatus === "bundle_draft";
}

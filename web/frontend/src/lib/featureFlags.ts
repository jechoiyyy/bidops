import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { FeatureFlagsResponse } from "./types";

/**
 * 이 환경에서 꺼진 기능을 요청 전에 알린다(설계고도화안 C-4, contracts.md "기능 스위치").
 *
 * - `off`: 서버가 `false`라고 답했다 — 요청 control을 막고 "이 환경에서 꺼져 있음"을 먼저 보인다.
 * - `on`: 서버가 `true`라고 답했다 — 다른 전제는 각 API가 판단한다(켜짐 ≠ 준비 완료).
 * - `unknown`: 아직 모르거나 조회에 실패했다 — 켜져 있다고 가정하지 않고, 기존 요청·오류 경로를
 *   그대로 둔다(신호가 없다고 기능을 숨기지 않는다).
 */
export type FeatureState = "on" | "off" | "unknown";
export type FeatureKey = Exclude<keyof FeatureFlagsResponse, "schema_version">;

export const FEATURE_OFF_LABEL = "이 환경에서 꺼져 있음";

export function useFeatureFlags() {
  const query = useQuery({
    queryKey: ["feature-flags"],
    queryFn: ({ signal }) => api.getFeatureFlags({ signal }),
    staleTime: 5 * 60_000,
    retry: false,
  });
  const state = (key: FeatureKey): FeatureState => {
    if (!query.isSuccess) return "unknown";
    return query.data[key] === true ? "on" : query.data[key] === false ? "off" : "unknown";
  };
  /** 신호가 정해졌는가(성공 또는 실패). 기다릴 필요가 없으면 `true`다. */
  const settled = query.isSuccess || query.isError;
  return { state, settled };
}

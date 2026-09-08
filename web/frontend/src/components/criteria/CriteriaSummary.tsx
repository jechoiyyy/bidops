import { useQuery } from "@tanstack/react-query";
import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { api } from "../../lib/api";
import type { ProfileErrorCode, ProfileSectionsResponse, ProfileUnknownsResponse } from "../../lib/types";
import { Small, StatusToken, shortIdentifier } from "./CriteriaPrimitives";

/**
 * 네 탭 위에 한 줄로 남는 요약 (승인 시안 `.context-strip`).
 *
 * 옛 고정 2열 경계 패널을 대신하는 자리 가운데 하나다. 여기서 말하는 것은 셋뿐이다.
 *
 *  1. **기준 프로필 버전과 읽기 전용.** 이 화면에 프로필 편집 API가 없다는 사실은
 *     사라지지 않는다.
 *  2. **운영 활성 정책.** 없으면 "운영 활성 없음"이고, 조회를 못 했으면 "미확인"이다.
 *     둘은 다른 상태다.
 *  3. **미확인 항목 수.** 조회 실패는 0건이 아니라 확인 불가다.
 *
 * 무거운 조회(`/profile/sections`의 절 트리 전체)는 회사 프로필 탭에서만 나간다.
 * 여기서 읽는 둘은 각각 회사 프로필·판정 정책 탭이 이미 쓰는 query key와 같아
 * 탭을 열어도 요청이 늘지 않는다.
 */

function hasUnknownsPayload(data: ProfileUnknownsResponse | undefined): boolean {
  return Boolean(
    data
    && data.schema_version === "bidops.profile-projection.v1"
    && typeof data.profile_version === "string"
    && typeof data.total === "number"
    && Array.isArray(data.items),
  );
}

/** 사본 자체를 읽지 못한 상태. 이때의 "미확인 0건"은 아는 0이 아니다. */
const READ_FAILURE_CODES: ProfileErrorCode[] = [
  "profile_snapshot_unavailable",
  "profile_source_unavailable",
  "profile_yaml_unclosed",
  "profile_yaml_invalid",
];

function hasReadFailure(codes: unknown): boolean {
  return Array.isArray(codes) && codes.some((code) => READ_FAILURE_CODES.includes(code as ProfileErrorCode));
}

export function CriteriaSummary({ onShowUnknowns }: { onShowUnknowns: () => void }) {
  const unknownsQuery = useQuery({
    queryKey: ["profile-unknowns"],
    queryFn: api.getProfileUnknowns,
    staleTime: 30_000,
  });
  const policiesQuery = useQuery({
    queryKey: ["policies"],
    queryFn: ({ signal }) => api.getPolicies({}, { signal }),
    staleTime: 30_000,
  });
  // 절 트리는 회사 프로필 탭의 몫이다. `enabled: false`는 **새 요청을 내보내지
  // 않고 캐시에 이미 있는 것만** 읽는다. 그 응답이 사본 읽기 실패를 말하고 있으면
  // 미확인 항목의 "0건"은 아는 0이 아니므로 확인 불가로 적는다. 캐시가 비어 있는
  // 다른 탭에서는 미확인 응답 자신의 신호만으로 판단한다.
  const sectionsCache = useQuery<ProfileSectionsResponse>({
    queryKey: ["profile-sections"],
    queryFn: api.getProfileSections,
    enabled: false,
    staleTime: 30_000,
  });

  const profileReadFailure = sectionsCache.isError
    || hasReadFailure(sectionsCache.data?.error_codes)
    || hasReadFailure(unknownsQuery.data?.error_codes);
  const unknownsUsable = hasUnknownsPayload(unknownsQuery.data) && !profileReadFailure;
  const profileVersion = unknownsQuery.isPending
    ? "확인 중"
    : unknownsUsable
      ? unknownsQuery.data?.profile_version ?? "미확인"
      : "미확인";
  const unknownTotal = unknownsUsable ? unknownsQuery.data?.total ?? null : null;
  const activePolicy = policiesQuery.isPending
    ? "확인 중"
    : policiesQuery.isSuccess
      ? policiesQuery.data.active_policy_version ?? "운영 활성 없음"
      : "미확인";

  return (
    <div className="crit-summary" aria-label="판정 기준 요약">
      <span className="crit-summary-item">
        <Small>기준 프로필</Small>
        {/* 전문은 title과 사본 정보 창에 그대로 있다. 요약 줄만 줄여 적는다. */}
        <span title={profileVersion}>
          <Text as="span" className="crit-summary-value crit-mono">{shortIdentifier(profileVersion)}</Text>
        </span>
        <StatusToken label="읽기 전용" />
      </span>
      <span className="crit-summary-item">
        <Small>판정 정책</Small>
        <Text as="span" className="crit-summary-value crit-mono">{activePolicy}</Text>
        {policiesQuery.isError ? <Small>정책 목록 조회 실패 · 활성 정책 없음을 뜻하지 않습니다</Small> : null}
      </span>
      <span className="crit-summary-end">
        <Button
          label={unknownTotal === null ? "미확인 항목 · 확인 불가" : `미확인 항목 ${unknownTotal.toLocaleString("ko-KR")}`}
          onClick={onShowUnknowns}
          size="sm"
          variant="ghost"
        />
      </span>
    </div>
  );
}

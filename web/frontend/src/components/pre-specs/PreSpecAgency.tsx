import { AgencyFeature } from "../common/ReviewPrimitives";
import { shortDateLabel } from "../../lib/deadline";
import { agencyOf } from "../../lib/preSpecViews";
import type { PreSpecListItem } from "../../lib/types";

/**
 * 사전규격의 기관 두 이름과 검토 제외 기록 — 목록 행·목록 우측 상세·상세 페이지
 * 머리가 같은 규칙을 쓰도록 여기 한 벌만 둔다(F2, spec §6.2).
 *
 * `demand_agency`(원문 `rlDminsttNm`)는 **실제 발주처인 수요기관**이고 `agency`는
 * 그 건을 대행해 공고한 기관이다. 값이 없으면 직접 공고이므로 지금처럼
 * `agency`만 `발주기관`으로 둔다 — `agency`를 `수요기관`으로 재명명하지 않는다.
 * fallback 값이기 때문이다(spec §5). 입찰공고에는 이 필드가 없다.
 */

/** 값이 있을 때만 수요기관이다. 빈 문자열을 이름으로 쓰지 않는다. */
export function demandAgencyOf(item: Pick<PreSpecListItem, "demand_agency">): string | null {
  return item.demand_agency?.trim() || null;
}

function trimmed(value: string | null | undefined): string | null {
  return value?.trim() || null;
}

/**
 * 상세 머리의 기관 블록 — **수요기관을 크게, 공고(대행)기관을 작게**
 * (M5 승인 2026-09-22). 공용 강조 블록(`AgencyFeature`)의 부제 슬롯(`sub`)에
 * 공고기관을 넣어 한 블록으로 읽히게 한다(S1). 수요기관이 없으면 부제 없이
 * 블록 하나로 되돌아간다.
 */
export function PreSpecAgencyFeature({
  agency,
  className,
  demandAgency,
}: {
  agency: string | null;
  className?: string;
  demandAgency: string | null;
}) {
  const demand = trimmed(demandAgency);
  if (!demand) {
    return <AgencyFeature className={className} name={agency} fallback="발주기관 미확인" />;
  }
  return (
    <AgencyFeature
      className={className}
      label="수요기관"
      name={demand}
      fallback="수요기관 미확인"
      /* 공고기관은 부제다. 이름을 지어내지 않고 없으면 `미확인`으로 남긴다. */
      sub={`공고기관 ${trimmed(agency) ?? "미확인"}`}
      subClassName="pre-spec-announcer-agency"
    />
  );
}

/**
 * 목록 행의 기관 한 줄 — `{수요기관} · {공고기관} 대행`이고 대행기관은 작은
 * 글자로 뒤에 붙는다. 수요기관이 없으면 지금과 같이 `agency` 하나다.
 */
export function PreSpecRowAgency({ item }: { item: PreSpecListItem }) {
  const demand = demandAgencyOf(item);
  const announcer = trimmed(item.agency);
  if (!demand) return <>{agencyOf(item)}</>;
  return (
    <>
      {demand}
      {announcer ? <span className="pre-specs-row-agency-proxy"> · {announcer} 대행</span> : null}
    </>
  );
}

/**
 * 검토 제외 기록 한 줄 — 누가 · 언제 · 왜. **값이 없는 항목은 빼고** 셋 다
 * 없으면 `사유 미기록`이다. 빈 값을 다른 담당자·사유로 바꾸지 않는다.
 * 날짜는 목록 행의 마감 표기와 같은 월·일 축약(`09.21`)을 쓴다.
 */
export function preSpecExclusionRecord(item: PreSpecListItem): string {
  const parts = [
    trimmed(item.review_exclusion_actor_name),
    shortDateLabel(item.review_exclusion_changed_at),
    trimmed(item.review_exclusion_reason),
  ].filter((part): part is string => Boolean(part));
  return parts.length > 0 ? parts.join(" · ") : "사유 미기록";
}

/** 제외 기록을 라벨과 함께 한 줄로. 제외된 건에서만 그린다. */
export function PreSpecExclusionRecord({
  className,
  item,
  label = "제외 기록",
}: {
  className?: string;
  item: PreSpecListItem;
  label?: string;
}) {
  if (item.review_exclusion_status !== "excluded") return null;
  return (
    <span className={className}>
      <span className="pre-spec-exclusion-label">{label}</span>
      <span aria-hidden="true">·</span>
      <span className="pre-spec-exclusion-value">{preSpecExclusionRecord(item)}</span>
    </span>
  );
}

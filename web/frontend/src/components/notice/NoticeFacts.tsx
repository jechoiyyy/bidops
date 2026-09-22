import { Panel } from "../common/Panel";
import type { NoticeDetailResponse } from "../../lib/types";
import { formatDate, formatDateTime, formatPrice, formatTime, present } from "../../lib/format";

interface NoticeFactsProps {
  notice: NoticeDetailResponse;
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

/**
 * 원문 `budget`은 배정예산 → 추정가격 → 기초금액 순으로 채워진 값이므로
 * (`skills/bidops-collect/scripts/collect_notices.py:612`) '배정예산'이라 부르지
 * 않는다. `estimated_price`와 값이 같아도 한 칸으로 합치지 않는다 — 어느 쪽이
 * 원문에서 온 값인지 읽는 사람이 알 수 없게 된다(spec §6.3).
 */
function budgetLabel(value: number | null): string {
  return value === null || value === undefined || Number.isNaN(value)
    ? "예산 미제공"
    : formatPrice(value);
}

/**
 * 개찰일시는 `lifecycle.opening_at`이고 값이 없는 회차에서는 **키 자체가 없다**
 * (적재기가 null을 snapshot에 넣지 않는다 — `loader.py:672`). 그래서 키 존재를
 * 확인하고 없으면 `미제공`으로 남기며, 다른 일시로 대신하지 않는다.
 */
function openingLabel(lifecycle: Record<string, unknown>): string {
  if (!("opening_at" in lifecycle)) return "미제공";
  const value = lifecycle.opening_at;
  if (typeof value !== "string" || !value.trim()) return "미제공";
  return formatDateTime(value);
}

function flag(record: Record<string, unknown>, key: string, yes: string, no: string): string {
  const value = record[key];
  if (value === "Y" || value === true) return yes;
  if (value === "N" || value === false) return no;
  return "미확인";
}

export function NoticeFacts({ notice }: NoticeFactsProps) {
  const qualification = asRecord(notice.qualification_flags);
  const region = asRecord(notice.region_limit);
  const lifecycle = asRecord(notice.lifecycle);
  // `regional_joint_contract_limit`(collect_notices.py의 cmmnSpldmdCorpRgnLmtYn)은
  // 지역의무공동도급 구성원에 한정된 지역 제한 여부일 뿐, 공고 전체의 지역 제한 유무를
  // 말하지 않는다. "N"과 빈 값을 같은 뜻으로 볼 근거가 없으므로 둘 다 미확인으로 둔다.
  // "있음"만 basis 값 또는 "Y"라는 명시 근거가 있을 때 표시한다.
  const regionLabel = region.regional_joint_contract_limit === "Y" || region.basis
    ? present(region.basis, "지역 제한 있음")
    : "지역 제한 미확인";
  const participation = flag(qualification, "participation_limited", "참가 제한 있음", "참가 제한 없음");
  const industry = flag(qualification, "industry_limited", "업종 제한 있음", "업종 제한 없음");
  const restriction = `${regionLabel} · ${participation} · ${industry}`;
  const bidIdentifier = notice.bid_no
    ? notice.bid_ord
      ? `${notice.bid_no}-${notice.bid_ord}`
      : notice.bid_no
    : null;
  const method = [notice.method, qualification.joint_contract_method]
    .filter((value) => typeof value === "string" && value.trim())
    .join(" · ");

  return (
    <Panel className="notice-facts-panel" title="공고 정보" action={<span className="panel-note">나라장터 제공 값</span>}>
      <dl className="notice-facts">
        <dt>입찰공고번호</dt>
        <dd className="mono tabular-nums">{present(bidIdentifier, "식별자 미확인")}</dd>
        <dt>공고명</dt>
        <dd>{present(notice.title, "공고명 미확인")}</dd>
        <dt>발주기관</dt>
        <dd>{present(notice.agency, "발주기관 미확인")}</dd>
        <dt>예산 (원문 제공 금액)</dt>
        <dd className="mono tabular-nums">{budgetLabel(notice.budget)}</dd>
        <dt>추정가격</dt>
        <dd className="mono tabular-nums">{formatPrice(notice.estimated_price)}</dd>
        <dt>개찰</dt>
        <dd className="mono tabular-nums">{openingLabel(lifecycle)}</dd>
        <dt>공고일</dt>
        <dd className="mono tabular-nums">{notice.published_at ? `${formatDate(notice.published_at)} · ${formatTime(notice.published_at).split(" ").pop()}` : "일자 미확인"}</dd>
        <dt>입찰방식</dt>
        <dd>{method || "입찰방식 미확인"}</dd>
        <dt>지역·참가제한</dt>
        <dd>{restriction}</dd>
      </dl>
    </Panel>
  );
}

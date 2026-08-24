import { Panel } from "../common/Panel";
import type { NoticeDetailResponse } from "../../lib/types";
import { formatDate, formatPrice, formatTime, present } from "../../lib/format";

interface NoticeFactsProps {
  notice: NoticeDetailResponse;
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
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
  const regionLabel = region.regional_joint_contract_limit === "Y" || region.basis
    ? present(region.basis, "지역 제한 있음")
    : "지역 제한 없음";
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
    <Panel className="notice-facts-panel" title="공고 정보" action={<span className="panel-note">나라장터 API</span>}>
      <dl className="notice-facts">
        <dt>입찰공고번호</dt>
        <dd className="mono tabular-nums">{present(bidIdentifier, "식별자 미확인")}</dd>
        <dt>공고명</dt>
        <dd>{present(notice.title, "공고명 미확인")}</dd>
        <dt>발주기관</dt>
        <dd>{present(notice.agency, "발주기관 미확인")}</dd>
        <dt>추정가격</dt>
        <dd className="mono tabular-nums">{formatPrice(notice.estimated_price)}</dd>
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

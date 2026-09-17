import { Token } from "@astryxdesign/core/Token";
import { ArrowRight } from "lucide-react";
import { EmptyState } from "../common/EmptyState";
import { describeApiError } from "../../lib/apiErrors";
import { CHANGE_STATUS_LABELS, formatMoment, shortHash } from "./labels";
import type {
  BidConditionChange,
  BidConditionField,
  BidConditionNotice,
  BidConditionPreSpecChange,
  BidConditionsView,
} from "./types";

/**
 * 공고 조건 요약(spec §9.1·§11.3).
 *
 * 서버가 수집 공고에서 결정적으로 읽은 값만 옮긴다. 모델 호출도 브라우저 재판정도
 * 없다. 표시 규칙은 셋이다.
 *
 * - `null`은 **값 없음**이다. 관측되지 않았다는 뜻이며 `N`·0·"없음"으로 읽지 않는다.
 * - 비교 상태 `unknown`은 **미확인**이다. 변경 없음으로 접지 않는다.
 * - 목록(`bid_notices`) 순서는 표시용이다. 최신 차수는 서버가 정한 `latest_notice_id`
 *   하나뿐이고, 그것이 없으면 목록 끝을 최신으로 대신하지 않는다.
 */

export const CONDITION_LABELS: Record<BidConditionField, string> = {
  budget: "예산",
  estimated_price: "추정가격",
  deadline_at: "입찰마감",
  opening_at: "개찰일",
  method: "계약방법",
  participation_limited: "참가제한",
  industry_limited: "업종제한",
  sw_industry_1468: "1468 업종 표시",
  joint_contract_method: "공동수급",
  successful_bid_method: "낙찰방법",
  technical_evaluation_rate: "기술평가비율",
  region_limit_basis: "지역제한 근거",
  joint_contract_regions: "공동수급 지역",
  change_reason: "정정 사유",
  re_notice: "재공고",
};

const PRE_SPEC_FIELD_LABELS: Record<BidConditionPreSpecChange["field"], string> = {
  budget: "예산",
  title: "사업명",
};

/** 표의 한 줄에 두 항목씩. 긴 문장인 정정 사유는 마지막 줄을 혼자 쓴다. */
const TABLE_ROWS: Array<[BidConditionField, BidConditionField | null]> = [
  ["budget", "estimated_price"],
  ["deadline_at", "opening_at"],
  ["method", "successful_bid_method"],
  ["participation_limited", "industry_limited"],
  ["sw_industry_1468", "technical_evaluation_rate"],
  ["joint_contract_method", "joint_contract_regions"],
  ["region_limit_basis", "re_notice"],
  ["change_reason", null],
];

const FLAG_GLOSS: Partial<Record<BidConditionField, { Y: string; N: string }>> = {
  participation_limited: { Y: "Y · 제한 있음", N: "N · 제한 없음" },
  industry_limited: { Y: "Y · 제한 있음", N: "N · 제한 없음" },
  sw_industry_1468: { Y: "Y · 1468 표시 있음", N: "N · 1468 표시 없음" },
  re_notice: { Y: "Y · 재공고", N: "N · 재공고 아님" },
};

/** Decimal 문자열의 정수부에만 자릿점을 넣는다. 수치로 바꾸지 않아 자릿수를 잃지 않는다. */
function formatAmount(value: string): string {
  const match = /^(-?)(\d+)(\.\d+)?$/.exec(value);
  if (!match) return value;
  const [, sign, integer, fraction = ""] = match;
  return `${sign}${integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${fraction}원`;
}

/** 조건 값 하나를 사람이 읽는 문자로. 해석은 표시 변환뿐이고 모르는 값은 그대로 둔다. */
export function formatConditionValue(field: BidConditionField, value: unknown): string {
  if (value === null || value === undefined) return "값 없음";
  if (Array.isArray(value)) {
    return value.length === 0 ? "지정 지역 없음" : value.map((item) => String(item)).join(", ");
  }
  const text = String(value);
  if (field === "budget" || field === "estimated_price") return formatAmount(text);
  if (field === "deadline_at" || field === "opening_at") return formatMoment(text);
  const gloss = FLAG_GLOSS[field];
  if (gloss && (text === "Y" || text === "N")) return gloss[text];
  return text;
}

export function noticeRoundLabel(notice: Pick<BidConditionNotice, "bid_no" | "bid_ord">): string {
  return `${notice.bid_no ?? "공고번호 값 없음"} · 차수 ${notice.bid_ord ?? "값 없음"}`;
}

export function latestConditionNotice(view: BidConditionsView | undefined): BidConditionNotice | null {
  if (!view || view.latest_notice_id === null) return null;
  return view.bid_notices.find((notice) => notice.notice_id === view.latest_notice_id) ?? null;
}

function ChangeValues({ field, before, after }: { field: BidConditionField; before: unknown; after: unknown }) {
  return (
    <span className="bid-delta-condition-change-values">
      <span>{formatConditionValue(field, before)}</span>
      <ArrowRight aria-hidden="true" />
      <span className="visually-hidden">→</span>
      <span>{formatConditionValue(field, after)}</span>
    </span>
  );
}

function RoundChanges({ previous, notice, isLatest }: { previous: BidConditionNotice; notice: BidConditionNotice; isLatest: boolean }) {
  const changed = notice.changes_from_previous.filter((change) => change.status === "changed");
  const unknown = notice.changes_from_previous.filter((change) => change.status === "unknown");
  const unchanged = notice.changes_from_previous.filter((change) => change.status === "unchanged");
  const line = (change: BidConditionChange) => (
    <li key={change.field} data-change-status={change.status} data-condition-field={change.field}>
      <Token size="sm" label={CHANGE_STATUS_LABELS[change.status]} />
      <strong>{CONDITION_LABELS[change.field]}</strong>
      <ChangeValues field={change.field} before={change.before} after={change.after} />
    </li>
  );
  return (
    <article className="bid-delta-round" aria-label={`${noticeRoundLabel(previous)}에서 ${noticeRoundLabel(notice)}로`}>
      <header className="bid-delta-round-heading">
        <strong>
          {noticeRoundLabel(previous)} → {noticeRoundLabel(notice)}
          {isLatest ? " (최신)" : ""}
        </strong>
        <span className="bid-delta-muted">
          변경 {changed.length}건 · 미확인 {unknown.length}건 · 변경 없음 {unchanged.length}건
        </span>
      </header>
      {changed.length > 0 ? <ul className="bid-delta-round-list bid-delta-round-changed">{changed.map(line)}</ul> : null}
      {unknown.length > 0 ? <ul className="bid-delta-round-list">{unknown.map(line)}</ul> : null}
      {changed.length === 0 && unknown.length === 0 ? (
        <p className="bid-delta-help">이 차수에서 확인된 변경은 없습니다. 비교한 항목이 모두 같은 값입니다.</p>
      ) : null}
      {unchanged.length > 0 ? (
        <details className="bid-delta-technical-details">
          <summary>변경 없음 {unchanged.length}개 항목 보기</summary>
          <p className="bid-delta-help">{unchanged.map((change) => CONDITION_LABELS[change.field]).join(" · ")}</p>
        </details>
      ) : null}
    </article>
  );
}

function PreSpecComparison({ view }: { view: BidConditionsView }) {
  return (
    <section className="bid-delta-conditions-sub" aria-labelledby="bid-delta-prespec-compare-title">
      <div className="bid-delta-panel-heading">
        <h4 id="bid-delta-prespec-compare-title">사전규격 대비</h4>
        <span className="bid-delta-muted">
          {view.pre_spec ? `사전규격 공고 ID ${view.pre_spec.notice_id}` : "확정 연결된 사전규격 없음"}
        </span>
      </div>
      {view.pre_spec ? (
        view.pre_spec_comparison.length > 0 ? (
          <ul className="bid-delta-round-list">
            {view.pre_spec_comparison.map((change) => (
              <li key={change.field} data-change-status={change.status} data-prespec-field={change.field}>
                <Token size="sm" label={CHANGE_STATUS_LABELS[change.status]} />
                <strong>{PRE_SPEC_FIELD_LABELS[change.field]}</strong>
                <span className="bid-delta-condition-change-values">
                  <span>{change.field === "budget" ? formatConditionValue("budget", change.before) : change.before ?? "값 없음"}</span>
                  <ArrowRight aria-hidden="true" />
                  <span className="visually-hidden">→</span>
                  <span>{change.field === "budget" ? formatConditionValue("budget", change.after) : change.after ?? "값 없음"}</span>
                </span>
              </li>
            ))}
          </ul>
        ) : <p className="bid-delta-help">서버가 비교 항목을 주지 않았습니다. 변경 없음으로 해석하지 않습니다.</p>
      ) : (
        <p className="bid-delta-help">확정 연결된 사전규격이 없어 예산·사업명을 비교하지 않았습니다. 사전규격이 없다는 뜻은 아닙니다.</p>
      )}
      {view.not_comparable.includes("deadline_at") ? (
        <p className="bid-delta-help" data-not-comparable="deadline_at">비교 불가: 입찰 마감(사전규격 의견등록마감과 의미가 다름)</p>
      ) : null}
    </section>
  );
}

export function BidConditionsSection({
  view,
  isPending,
  error,
  onRetry,
}: {
  view: BidConditionsView | undefined;
  isPending: boolean;
  error: unknown;
  onRetry: () => void;
}) {
  const latest = latestConditionNotice(view);
  return (
    <section className="bid-delta-conditions" aria-labelledby="bid-delta-conditions-title">
      <div className="bid-delta-panel-heading">
        <h3 id="bid-delta-conditions-title">공고 조건</h3>
        <span className="bid-delta-muted">
          {latest
            ? `최신 차수 ${noticeRoundLabel(latest)} · 게시 ${formatMoment(latest.published_at)}`
            : "수집 공고의 결정적 값 · 모델 호출 없음"}
        </span>
      </div>

      {isPending ? (
        <p className="bid-delta-page-status" role="status">공고 조건을 불러오는 중입니다.</p>
      ) : error || !view ? (
        <EmptyState
          compact
          tone="error"
          title="공고 조건을 불러오지 못했습니다."
          description="조회 실패를 조건 없음이나 변경 없음으로 해석하지 않습니다."
          problem={describeApiError(error, "공고 조건을 확인할 수 없습니다.")}
          action={{ label: "공고 조건 다시 읽기", onClick: onRetry }}
        />
      ) : view.bid_notices.length === 0 ? (
        <p className="bid-delta-help">확정 연결된 입찰공고가 없어 공고 조건을 표시할 수 없습니다. 입찰공고가 없다는 뜻은 아닙니다.</p>
      ) : (
        <>
          {latest ? (
            <table className="bid-delta-conditions-table" aria-label={`최신 차수 공고 조건 · ${noticeRoundLabel(latest)}`}>
              <tbody>
                {TABLE_ROWS.map(([left, right]) => (
                  <tr key={left}>
                    <th scope="row">{CONDITION_LABELS[left]}</th>
                    <td data-condition-field={left} colSpan={right ? 1 : 3}>{formatConditionValue(left, latest.conditions[left])}</td>
                    {right ? (
                      <>
                        <th scope="row">{CONDITION_LABELS[right]}</th>
                        <td data-condition-field={right}>{formatConditionValue(right, latest.conditions[right])}</td>
                      </>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="bid-delta-help" role="status">
              최신 차수를 확정할 수 없습니다. 게시 시각이 없는 차수가 있어 목록 순서로 최신을 대신하지 않으며, 최신 차수 조건을 표시하지 않습니다.
            </p>
          )}
          {latest ? (
            <p className="bid-delta-help">
              공고 ID {latest.notice_id} · 관측 해시 <span className="mono">{shortHash(latest.observation_sha256)}</span>
              {" · "}값 없음은 수집에서 관측되지 않은 값입니다.
            </p>
          ) : null}

          <section className="bid-delta-conditions-sub" aria-labelledby="bid-delta-round-changes-title">
            <div className="bid-delta-panel-heading">
              <h4 id="bid-delta-round-changes-title">차수 간 변경</h4>
              <span className="bid-delta-muted">차수 {view.bid_notices.length}개 · 공고번호·차수 순</span>
            </div>
            {view.bid_notices.length < 2 ? (
              <p className="bid-delta-help">차수가 하나여서 비교할 이전 차수가 없습니다.</p>
            ) : (
              <div className="bid-delta-round-stack">
                {view.bid_notices.slice(1).map((notice, index) => (
                  <RoundChanges
                    key={notice.notice_id}
                    previous={view.bid_notices[index]}
                    notice={notice}
                    isLatest={notice.notice_id === view.latest_notice_id}
                  />
                ))}
              </div>
            )}
          </section>
        </>
      )}

      {view && !isPending && !error ? <PreSpecComparison view={view} /> : null}
    </section>
  );
}

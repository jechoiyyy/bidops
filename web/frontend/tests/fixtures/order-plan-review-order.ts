import { orderPlanStaleReason, plannedMonthKey } from "../../src/components/order-plans/orderPlanReviewFacts";

const KST_DATE_PARTS = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Seoul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/**
 * `관련`·`불확실` 보기의 검토 순서. 테스트 데이터의 페이지를 구성할 때 적용한다.
 * 1) 예정월이 지나지 않았고 공고도 없는 건이 앞, 그 안에서 예정월이 가까운 순(미확인 월은 뒤),
 * 2) 같으면 최근 첫 수집 순, 3) 예정월 지남·공고 게시됨은 뒤에 같은 규칙으로. 같으면 서버 순서를 지킨다.
 */
export function sortForReview<T extends {
  planned_order_year: string | null; planned_order_month: string | null; notice_posted: string | null; first_observed_at: string | null;
}>(items: readonly T[], nowMonth: string): T[] {
  return items
    .map((item, index) => {
      const observed = item.first_observed_at ? Date.parse(item.first_observed_at) : Number.NaN;
      return { item, index, stale: orderPlanStaleReason(item, nowMonth) !== null, month: plannedMonthKey(item), observed: Number.isFinite(observed) ? observed : -Infinity };
    })
    .sort((left, right) =>
      Number(left.stale) - Number(right.stale)
      || (left.stale ? 0 : (left.month ?? "9999-99").localeCompare(right.month ?? "9999-99"))
      || (right.observed === left.observed ? 0 : right.observed > left.observed ? 1 : -1)
      || left.index - right.index)
    .map(({ item }) => item);
}

/**
 * 수집일: `first_observed_at`의 한국 시간 날짜(`YYYY-MM-DD`). 읽을 수 없으면 `null`(미확인)이다.
 * BM25 순위는 **수집일마다** 따로 매겨지므로(일일 실행 하나가 그날 모집단 하나를 줄 세운다)
 * 순위를 비교하려면 이 값이 먼저 같아야 한다.
 */
export function collectionDayKst(value: string | null | undefined): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  const parts = Object.fromEntries(KST_DATE_PARTS.formatToParts(parsed).map((part) => [part.type, part.value])) as
    Record<"year" | "month" | "day", string>;
  return `${parts.year}-${parts.month}-${parts.day}`;
}

interface RankSortable {
  first_observed_at: string | null;
  stage1_rank: number | null;
}

interface RankSortKey {
  index: number;
  day: string | null;
  rank: number | null;
  observed: number;
}

function rankSortKey(item: RankSortable, index: number): RankSortKey {
  const observed = item.first_observed_at ? Date.parse(item.first_observed_at) : Number.NaN;
  return {
    index,
    day: collectionDayKst(item.first_observed_at),
    rank: item.stage1_rank,
    observed: Number.isFinite(observed) ? observed : -Infinity,
  };
}

/**
 * 수집일 최신 → 그날 BM25 순위 오름차순(순위 없음은 뒤) → 최근 첫 수집 → 서버 순서.
 *
 * 수집일이 다르면 순위를 보지 않는다 — 다른 날의 1위와 2위는 서로 비교할 수 없다. 수집일을
 * 모르는 건(`null`)은 맨 뒤이며 그 안에서도 순위를 비교하지 않는다(같은 날인지 모른다).
 */
function compareByDayThenRank(left: RankSortKey, right: RankSortKey): number {
  if (left.day !== right.day) {
    if (left.day === null) return 1;
    if (right.day === null) return -1;
    return right.day.localeCompare(left.day);
  }
  if (left.day !== null && left.rank !== right.rank) {
    if (left.rank === null) return 1;
    if (right.rank === null) return -1;
    return left.rank - right.rank;
  }
  return (right.observed === left.observed ? 0 : right.observed > left.observed ? 1 : -1)
    || left.index - right.index;
}

/**
 * `불확실`(훑어보기) 보기의 순서(2026-11-18 수정안 3B). 지난 건(예정월 지남·공고 게시됨, `sortForReview`와
 * 같은 규칙)을 뒤로 보낸 뒤, 각 묶음 안에서 수집일 최신 → 그날 BM25 순위순이다.
 */
export function sortForBrowse<T extends RankSortable & {
  planned_order_year: string | null; planned_order_month: string | null; notice_posted: string | null;
}>(items: readonly T[], nowMonth: string): T[] {
  return items
    .map((item, index) => ({ item, stale: orderPlanStaleReason(item, nowMonth) !== null, key: rankSortKey(item, index) }))
    .sort((left, right) => Number(left.stale) - Number(right.stale) || compareByDayThenRank(left.key, right.key))
    .map(({ item }) => item);
}

/** `모델 미판정` 보기의 순서(2026-11-18 수정안 3B): 수집일 최신 → 그날 BM25 순위순. 지난 건을 따로 보내지 않는다. */
export function sortByCollectionRank<T extends RankSortable>(items: readonly T[]): T[] {
  return items
    .map((item, index) => ({ item, key: rankSortKey(item, index) }))
    .sort((left, right) => compareByDayThenRank(left.key, right.key))
    .map(({ item }) => item);
}


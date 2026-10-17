/**
 * RL-01 `/briefing` 화면용 고정 응답(`GET /api/briefings/latest`·`/{date}`).
 *
 * 모양은 spec "REST (`bidops.briefing.v1`)"의 `BriefingView`·`BriefingItemView` 필드 목록에서
 * 옮겼다(응답에는 `score`·`policy_sha256`·`graph_version_id`가 없다). 값은 **fixture 작성자의
 * 창작값**이며 실제 공고가 아니다. 화면 시계는 테스트가 `BRIEFING_NOW`로 고정하므로 마감 D-n이
 * 결정적이다.
 */
import type { BriefingItemView, BriefingStage, BriefingView } from "../../src/lib/types";

/** 테스트가 `page.clock.setFixedTime`에 넘기는 시각(2026-10-16 금요일 09:00 KST). */
export const BRIEFING_NOW = "2026-10-16T09:00:00+09:00";
export const BRIEFING_DATE = "2026-10-16";
export const BRIEFING_PREVIOUS_DATE = "2026-10-15";
/** 월요일 브리핑 — 직전 평일은 지난 금요일이다. */
export const BRIEFING_MONDAY_DATE = "2026-10-19";

export const LONG_TITLE =
  "대구경북광역행정통합지원센터정보시스템통합고도화및클라우드전환사업관련제안요청서사전규격공개건의모든세부요구사항검토대상";

/** 결정적 UUID. 끝 두 자리가 항목 번호다. */
export function briefingItemId(index: number): string {
  return `b1000000-0000-4000-8000-0000000000${String(index).padStart(2, "0")}`;
}

interface ItemSeed {
  index: number;
  stage: BriefingStage;
  title: string;
  agency: string;
  amount_krw: number | null;
  deadline_at: string | null;
  deadline_kind: BriefingItemView["deadline_kind"];
  planned_month?: string | null;
  verdict_display?: BriefingItemView["verdict_display"];
  reasons?: BriefingItemView["reasons"];
  blocking?: BriefingItemView["blocking"];
  reaction?: BriefingItemView["reaction"];
  reacted_by?: string | null;
  reacted_at?: string | null;
  reacted_via?: BriefingItemView["reacted_via"];
  revision?: number;
  kind?: BriefingItemView["kind"];
  change_fields?: string[];
}

function item(seed: ItemSeed): BriefingItemView {
  const tracked = seed.kind === "tracked_change";
  return {
    item_id: briefingItemId(seed.index),
    kind: seed.kind ?? "recommendation",
    rank: tracked ? null : seed.index,
    stage: seed.stage,
    notice_id: seed.stage === "order_plan" ? null : 9000 + seed.index,
    order_plan_id: seed.stage === "order_plan" ? 7000 + seed.index : null,
    opportunity_id: 500 + seed.index,
    title: seed.title,
    agency: seed.agency,
    amount_krw: seed.amount_krw,
    deadline_at: seed.deadline_at,
    deadline_kind: seed.deadline_kind,
    planned_month: seed.planned_month ?? null,
    verdict_display: seed.verdict_display ?? "분석 대기",
    reasons: seed.reasons ?? [],
    blocking: seed.blocking ?? [],
    change_fields: seed.change_fields ?? [],
    reaction: tracked ? null : seed.reaction ?? "대기",
    reacted_by: seed.reacted_by ?? null,
    reacted_at: seed.reacted_at ?? null,
    reacted_via: seed.reacted_via ?? null,
    revision: seed.revision ?? 0,
    record_path: `/opportunities/${500 + seed.index}`,
  };
}

/** 반응 대기 3건(1·2·3), 채택·무시·나중에 각 1건(4·5·6), 추적 변화 2건(7·8). */
export function briefingFixture(): BriefingView {
  const items = [
    item({
      index: 1,
      stage: "pre_spec",
      title: "클라우드 기반 업무시스템 고도화 사전규격",
      agency: "대구광역시",
      amount_krw: 480_000_000,
      deadline_at: "2026-10-18T18:00:00+09:00", // D-2 → 강조
      deadline_kind: "opinion_close",
      reasons: [
        { kind: "keyword", text: "클라우드" },
        { kind: "similar_project", count: 2 },
        { kind: "repeat_agency", text: "대구광역시" },
      ],
    }),
    item({
      index: 2,
      stage: "bid_notice",
      title: "정보시스템 통합 유지관리 용역",
      agency: "경상북도",
      amount_krw: 1_250_000_000,
      deadline_at: "2026-10-28T10:00:00+09:00", // D-12 → 강조 없음
      deadline_kind: "bid_close",
      reasons: [{ kind: "keyword", text: "유지관리" }],
    }),
    item({
      index: 3,
      stage: "order_plan",
      title: "2027년 차세대 민원 포털 구축",
      agency: "대구광역시 수성구",
      amount_krw: null, // 금액 미공개
      deadline_at: null,
      deadline_kind: "planned_month",
      planned_month: "2027-02",
      verdict_display: "연차 추적",
      reasons: [
        { kind: "similar_project", count: 3 },
        { kind: "repeat_agency", text: "대구광역시 수성구" },
      ],
    }),
    item({
      index: 4,
      stage: "pre_spec",
      title: LONG_TITLE,
      agency: "한국지역정보개발원",
      amount_krw: 320_000_000,
      deadline_at: "2026-10-23T18:00:00+09:00", // D-7 → 강조(경계)
      deadline_kind: "opinion_close",
      reaction: "채택",
      reacted_by: "김담당",
      reacted_at: "2026-10-16T08:41:00+09:00",
      reacted_via: "screen",
      revision: 1,
    }),
    item({
      index: 5,
      stage: "bid_notice",
      title: "서버 증설 및 보안 장비 도입",
      agency: "경북대학교",
      amount_krw: 90_000_000,
      deadline_at: "2026-10-24T18:00:00+09:00", // D-8 → 강조 없음(경계)
      deadline_kind: "bid_close",
      reaction: "무시",
      reacted_by: "박기획",
      reacted_at: "2026-10-16T08:50:00+09:00",
      reacted_via: "screen",
      revision: 1,
    }),
    item({
      index: 6,
      stage: "pre_spec",
      title: "통합 데이터 플랫폼 구축 사전규격",
      agency: "대구도시개발공사",
      amount_krw: 700_000_000,
      deadline_at: "2026-10-30T18:00:00+09:00",
      deadline_kind: "opinion_close",
      reaction: "나중에",
      reacted_by: "Kim",
      reacted_at: "2026-10-16T08:55:00+09:00",
      reacted_via: "slack",
      revision: 1,
    }),
  ];
  const trackedChanges = [
    item({
      index: 7,
      kind: "tracked_change",
      stage: "bid_notice",
      title: "도로 관리 시스템 재구축(정정공고)",
      agency: "경상북도 도로관리사업소",
      amount_krw: 560_000_000,
      deadline_at: "2026-10-21T17:00:00+09:00", // D-5
      deadline_kind: "bid_close",
      verdict_display: "재검토 중",
      change_fields: ["deadline_at"],
    }),
    item({
      index: 8,
      kind: "tracked_change",
      stage: "pre_spec",
      title: "스마트 시티 통합 플랫폼 사전규격(정정)",
      agency: "대구광역시",
      amount_krw: 810_000_000,
      deadline_at: "2026-11-05T18:00:00+09:00",
      deadline_kind: "opinion_close",
      verdict_display: "재검토 중",
      change_fields: ["title", "budget"],
    }),
  ];
  return {
    schema_version: "bidops.briefing.v1",
    briefing_date: BRIEFING_DATE,
    status: "generated",
    generated_at: "2026-10-16T08:00:17+09:00",
    item_count: items.length,
    slack_sent_at: null,
    items,
    tracked_changes: trackedChanges,
    collection_note: null,
  };
}

/** 이전 평일(2026-10-15 목) 브리핑. 항목 하나만 둔다. */
export function previousBriefingFixture(): BriefingView {
  const base = briefingFixture();
  const only = { ...base.items[1], item_id: briefingItemId(21), title: "전날 추천 공고(정보보호 컨설팅)" };
  return {
    ...base,
    briefing_date: BRIEFING_PREVIOUS_DATE,
    item_count: 1,
    items: [only],
    tracked_changes: [],
  };
}

/** 월요일(2026-10-19) 브리핑 — "이전 브리핑"이 지난 금요일을 가리키는지 본다. */
export function mondayBriefingFixture(): BriefingView {
  const base = briefingFixture();
  return {
    ...base,
    briefing_date: BRIEFING_MONDAY_DATE,
    item_count: 1,
    items: [{ ...base.items[0], item_id: briefingItemId(31), title: "월요일 추천 공고" }],
    tracked_changes: [],
  };
}

/** 추천 0건(수집은 정상). 서버는 `status=empty`로 준다. */
export function emptyBriefingFixture(): BriefingView {
  return {
    ...briefingFixture(),
    status: "empty",
    item_count: 0,
    items: [],
    tracked_changes: [],
    collection_note: null,
  };
}

/** 수집이 끝나지 않은 날. 항목은 그래도 만들어진다(spec "상태 값과 실패 처리"). */
export function incompleteBriefingFixture(note = "기준일 수집 회차 없음"): BriefingView {
  return { ...briefingFixture(), status: "collection_incomplete", collection_note: note };
}

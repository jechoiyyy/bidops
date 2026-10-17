/**
 * RL-02 `/opportunities/:id/*` 레코드 화면용 고정 응답.
 *
 * 모양은 spec "활동 피드 `GET /api/opportunities/{id}/activity`"의 `ActivityItem`·`stages[]`와 기존
 * `GET /api/opportunities/{id}`(`OpportunityDetailResponse`)·`GET /api/notices/{pk}`에서 옮겼다.
 * 값은 **fixture 작성자의 창작값**이며 실제 공고가 아니다. 화면 시계는 테스트가 `RECORD_NOW`로
 * 고정하므로 마감 D-n·`오늘` 표기가 결정적이다. 기대값은 화면 코드를 가져오지 않고 값으로 직접 적는다.
 *
 * 레코드(id):
 *   7101 발주계획+사전규격+입찰공고(마감 D-4), 계속 추적, 모든 사건 종류의 표본
 *   7102 발주계획만(연차 추적), 미선택
 *   7103 사전규격만(의견 마감 D-2), 계약방법 없음
 *   7104 입찰공고 마감 지남
 *   7105 권위 연결 없음(제목 `#7105`), 확인할 후보 1건
 *   7106 병합됨 → 7101
 *   7108 긴 피드(60건, 커서 페이지)
 *   7109 권위 입찰공고 2건: 옛 공고 A(id 작음·마감 지남)와 새 공고 B(D-5). 서버 대표는 B다
 *
 * `stages[].link_id`는 서버(`opportunity_stages.representatives`)가 고른 대표 권위 연결 id다.
 * 마감·개찰은 입찰공고 대표를 따르고 계약은 언제나 `null`이다.
 */
import type {
  OpportunityActivityItem,
  OpportunityDetailResponse,
  OpportunityLinkView,
  OpportunityStageEntry,
  OpportunityStageState,
} from "../../src/lib/types";

/** 2026-10-16 금요일 10:30 KST. */
export const RECORD_NOW = "2026-10-16T10:30:00+09:00";

export interface RecordFixture {
  detail: OpportunityDetailResponse;
  title: string;
  stages: OpportunityStageEntry[];
  items: OpportunityActivityItem[];
  mergedInto: number | null;
}

const blankLink: Omit<OpportunityLinkView, "id" | "stage" | "link_type" | "status"> = {
  search_strategy: null,
  attempted_strategies: [],
  agency_match: null,
  last_searched_at: null,
  evidence_external_no: null,
  evidence_bid_no: null,
  human_decision: null,
  reviewer_name: null,
  reviewed_at: null,
  review_reason: null,
  record_type: null,
  record_id: null,
  notice_id: null,
  order_plan_id: null,
  source_type: null,
  title: null,
  agency: null,
  external_id: null,
  budget: null,
  deadline_at: null,
  planned_order_year: null,
  planned_order_month: null,
  record_external_id: null,
};

export function orderPlanLink(
  id: number,
  title: string,
  agency: string,
  extra: Partial<OpportunityLinkView> = {},
): OpportunityLinkView {
  return {
    ...blankLink,
    id,
    stage: "order_plan",
    link_type: "official",
    status: "확정",
    record_type: "order_plan",
    record_id: id,
    order_plan_id: id,
    title,
    agency,
    external_id: `RL-OP-${id}`,
    record_external_id: `RL-OP-${id}`,
    ...extra,
  };
}

export function noticeLink(
  id: number,
  noticeId: number,
  sourceType: "pre_spec" | "bid_notice",
  title: string,
  agency: string,
  extra: Partial<OpportunityLinkView> = {},
): OpportunityLinkView {
  return {
    ...blankLink,
    id,
    stage: "notice",
    link_type: "official",
    status: "확정",
    record_type: sourceType,
    record_id: noticeId,
    notice_id: noticeId,
    source_type: sourceType,
    title,
    agency,
    external_id: `RL-N-${noticeId}`,
    record_external_id: `RL-N-${noticeId}`,
    ...extra,
  };
}

function detailOf(
  id: number,
  links: OpportunityLinkView[],
  state: Partial<OpportunityDetailResponse> = {},
): OpportunityDetailResponse {
  return {
    id,
    section: null,
    pending_candidate_link_count: 0,
    open_blocking_item_count: 0,
    tracking_status: "미선택",
    tracking_reason: null,
    tracking_selected_by: null,
    tracking_selected_at: null,
    recheck_signal: false,
    recheck_signal_at: null,
    recheck_signal_link_id: null,
    first_registered_stage: "order_plan",
    action_reasons: [],
    hold_review_due_at: null,
    links,
    ...state,
  };
}

interface RepresentativeIds {
  orderPlan?: number;
  preSpec?: number;
  bidNotice?: number;
}

function stagesOf(
  states: Array<[OpportunityStageState, string | null]>,
  ids: RepresentativeIds = {},
): OpportunityStageEntry[] {
  const keys = ["order_plan", "pre_spec", "bid_notice", "deadline", "opening", "contract"];
  const bid = ids.bidNotice ?? null;
  const linkIds = [ids.orderPlan ?? null, ids.preSpec ?? null, bid, bid, bid, null];
  return states.map(([state, at], index) => ({ key: keys[index], state, at, link_id: linkIds[index] }));
}

let sequence = 0;
function activity(
  kind: OpportunityActivityItem["kind"],
  at: string,
  title: string,
  extra: Partial<OpportunityActivityItem> = {},
): OpportunityActivityItem {
  sequence += 1;
  return {
    item_id: `${kind}:${String(sequence).padStart(4, "0")}`,
    kind,
    at,
    actor: null,
    title,
    detail: null,
    link: null,
    status_pill: null,
    ...extra,
  };
}

/** 응답 항목이 가진 초 단위를 화면이 노출하지 않는지 보려고 일부러 초를 넣는다. */
export const TODAY_NOTE_AT = "2026-10-16T08:41:27+09:00";
export const EXTERNAL_BID_URL = "https://www.g2b.go.kr/fixture/bid-9103";
export const BID_DEADLINE = "2026-10-20T18:00:00+09:00";

const FULL_TITLE = "클라우드 기반 통합정보시스템 구축";
const FULL_AGENCY = "해솔시청";

const full: RecordFixture = {
  title: FULL_TITLE,
  mergedInto: null,
  detail: detailOf(
    7101,
    [
      orderPlanLink(7001, "통합정보시스템 구축 계획", FULL_AGENCY, { budget: 1_500_000_000, planned_order_year: "2026", planned_order_month: "2026-09" }),
      noticeLink(7002, 9102, "pre_spec", "클라우드 기반 통합정보시스템 구축 사전규격", FULL_AGENCY, { deadline_at: "2026-09-30T18:00:00+09:00" }),
      noticeLink(7003, 9103, "bid_notice", FULL_TITLE, FULL_AGENCY, { budget: 1_450_000_000, deadline_at: BID_DEADLINE }),
    ],
    {
      tracking_status: "계속 추적",
      tracking_reason: "사업 범위가 맞아 후속 공고 확인",
      tracking_selected_by: "최담당",
      tracking_selected_at: "2026-10-15T14:05:00+09:00",
      first_registered_stage: "order_plan",
      section: "추적 중",
    },
  ),
  stages: stagesOf([
    ["done", "2026-08-03T09:00:00+09:00"],
    ["done", "2026-09-20T09:00:00+09:00"],
    ["current", "2026-10-14T09:12:00+09:00"],
    ["upcoming_deadline", BID_DEADLINE],
    ["unknown", null],
    ["unknown", null],
  ], { orderPlan: 7001, preSpec: 7002, bidNotice: 7003 }),
  items: [
    activity("note_added", TODAY_NOTE_AT, "공급사 의견을 주 후반에 정리", { actor: "홍길동" }),
    activity("action_added", "2026-10-16T08:30:00+09:00", "다음 행동: 입찰 참여 조건 확인", { actor: "최담당", detail: "담당 김실무" }),
    activity("action_added", "2026-10-15T16:00:00+09:00", "다음 행동: 제안서 목차 초안", { actor: "홍길동", detail: "담당 홍길동" }),
    activity("action_done", "2026-10-15T17:30:00+09:00", "홍길동이 완료: 제안서 목차 초안", { actor: "홍길동", item_id: "action_done:0003" }),
    activity("tracking_decided", "2026-10-15T14:05:00+09:00", "최담당이 계속 추적으로 결정", { actor: "최담당" }),
    activity("briefing_reacted", "2026-10-15T09:10:00+09:00", "홍길동이 채택", {
      actor: "홍길동",
      status_pill: "채택",
      link: { label: "브리핑에서 보기", path: "/briefing?date=2026-10-15&selected=b1000000-0000-4000-8000-000000000001" },
    }),
    activity("recheck_signal", "2026-10-14T18:00:00+09:00", "재확인 신호"),
    activity("notice_corrected", "2026-10-14T10:00:00+09:00", "정정 · 마감", {
      link: { label: "공고 보기", path: EXTERNAL_BID_URL },
    }),
    activity("bid_posted", "2026-10-14T09:12:00+09:00", "입찰공고 게시", {
      link: { label: "공고 보기", path: EXTERNAL_BID_URL },
    }),
    activity("pre_spec_opened", "2026-09-20T09:00:00+09:00", "사전규격 공개", {
      link: { label: "사전규격 보기", path: "/pre-specs/9102" },
    }),
    activity("order_plan_found", "2026-08-03T09:00:00+09:00", `발주계획 발견 · ${FULL_AGENCY}`, {
      link: { label: "발주계획 보기", path: "/order-plans/7001" },
    }),
  ],
};

const orderPlanOnly: RecordFixture = {
  title: "스마트 도시 통합플랫폼 고도화",
  mergedInto: null,
  detail: detailOf(
    7102,
    [orderPlanLink(7011, "스마트 도시 통합플랫폼 고도화", "바다시청", { budget: 450_000_000, planned_order_year: "2027", planned_order_month: "2027-03" })],
    { first_registered_stage: "order_plan" },
  ),
  stages: stagesOf([
    ["current", "2026-10-10T09:00:00+09:00"],
    ["pending", null],
    ["pending", null],
    ["unknown", null],
    ["unknown", null],
    ["unknown", null],
  ], { orderPlan: 7011 }),
  items: [
    activity("order_plan_found", "2026-10-10T09:00:00+09:00", "발주계획 발견 · 바다시청", {
      link: { label: "발주계획 보기", path: "/order-plans/7011" },
    }),
  ],
};

const preSpecOnly: RecordFixture = {
  title: "공공 데이터 품질관리 체계 구축 사전규격",
  mergedInto: null,
  detail: detailOf(
    7103,
    [noticeLink(7021, 9202, "pre_spec", "공공 데이터 품질관리 체계 구축 사전규격", "산들군청", { deadline_at: "2026-10-18T18:00:00+09:00" })],
    { first_registered_stage: "pre_spec" },
  ),
  stages: stagesOf([
    ["unknown", null],
    ["current", "2026-10-12T09:00:00+09:00"],
    ["pending", null],
    ["unknown", null],
    ["unknown", null],
    ["unknown", null],
  ], { preSpec: 7021 }),
  items: [
    activity("pre_spec_opened", "2026-10-12T09:00:00+09:00", "사전규격 공개", {
      link: { label: "사전규격 보기", path: "/pre-specs/9202" },
    }),
  ],
};

const bidPassed: RecordFixture = {
  title: "정보보안 관제 용역",
  mergedInto: null,
  detail: detailOf(
    7104,
    [noticeLink(7031, 9304, "bid_notice", "정보보안 관제 용역", "들판공단", { deadline_at: "2026-10-10T18:00:00+09:00" })],
    { first_registered_stage: "bid_notice", tracking_status: "보류", tracking_selected_by: "홍길동", tracking_selected_at: "2026-10-09T10:00:00+09:00" },
  ),
  stages: stagesOf([
    ["unknown", null],
    ["unknown", null],
    ["done", "2026-10-01T09:00:00+09:00"],
    ["done", "2026-10-10T18:00:00+09:00"],
    ["unknown", null],
    ["unknown", null],
  ], { bidNotice: 7031 }),
  items: [
    activity("bid_posted", "2026-10-01T09:00:00+09:00", "입찰공고 게시", { link: { label: "공고 보기", path: EXTERNAL_BID_URL } }),
  ],
};

const noAuthority: RecordFixture = {
  title: "#7105",
  mergedInto: null,
  detail: detailOf(
    7105,
    [
      {
        ...noticeLink(7041, 9405, "pre_spec", "후보 사전규격", "초원시", {}),
        link_type: "candidate",
        status: "후보 확인 대기",
        search_strategy: "normalized",
        attempted_strategies: ["full", "normalized"],
        agency_match: true,
      },
    ],
    { pending_candidate_link_count: 1, section: "조치 필요", action_reasons: ["candidate_pending"], first_registered_stage: "order_plan" },
  ),
  stages: stagesOf([
    ["unknown", null],
    ["unknown", null],
    ["unknown", null],
    ["unknown", null],
    ["unknown", null],
    ["unknown", null],
  ]),
  items: [],
};

const merged: RecordFixture = {
  title: "#7106",
  mergedInto: 7101,
  detail: detailOf(7106, []),
  stages: stagesOf([
    ["unknown", null],
    ["unknown", null],
    ["unknown", null],
    ["unknown", null],
    ["unknown", null],
    ["unknown", null],
  ]),
  items: [],
};

const longFeed: RecordFixture = {
  title: "장기 운영 데이터 이관 용역",
  mergedInto: null,
  detail: detailOf(
    7108,
    [noticeLink(7051, 9508, "bid_notice", "장기 운영 데이터 이관 용역", "언덕시청", { deadline_at: "2026-11-30T18:00:00+09:00" })],
    { first_registered_stage: "bid_notice" },
  ),
  stages: stagesOf([
    ["unknown", null],
    ["unknown", null],
    ["current", "2026-10-01T09:00:00+09:00"],
    ["upcoming_deadline", "2026-11-30T18:00:00+09:00"],
    ["unknown", null],
    ["unknown", null],
  ], { bidNotice: 7051 }),
  items: Array.from({ length: 60 }, (_, index) => activity(
    "note_added",
    new Date(Date.parse("2026-10-15T20:00:00+09:00") - index * 3_600_000).toISOString(),
    `기록 ${String(60 - index).padStart(2, "0")}`,
    { actor: "홍길동" },
  )),
};

/** 재공고: 같은 단계 권위 연결 2건. 연결 목록은 서버처럼 (단계, id) 순이라 옛 공고 A가 앞이다. */
export const REBID_OLD_DEADLINE = "2026-10-09T18:00:00+09:00";
export const REBID_NEW_DEADLINE = "2026-10-21T18:00:00+09:00";
const rebid: RecordFixture = {
  title: "통합 민원 포털 재구축 (재공고)",
  mergedInto: null,
  detail: detailOf(
    7109,
    [
      noticeLink(7061, 9601, "bid_notice", "통합 민원 포털 재구축", "강변구청", { budget: 300_000_000, deadline_at: REBID_OLD_DEADLINE }),
      noticeLink(7062, 9602, "bid_notice", "통합 민원 포털 재구축 (재공고)", "강변구청", { budget: 280_000_000, deadline_at: REBID_NEW_DEADLINE }),
    ],
    { first_registered_stage: "bid_notice" },
  ),
  stages: stagesOf([
    ["unknown", null],
    ["unknown", null],
    ["current", "2026-10-12T09:00:00+09:00"],
    ["upcoming_deadline", REBID_NEW_DEADLINE],
    ["unknown", null],
    ["unknown", null],
  ], { bidNotice: 7062 }),
  items: [
    activity("bid_posted", "2026-10-12T09:00:00+09:00", "입찰공고 게시", { link: { label: "공고 원문", path: "https://www.g2b.go.kr/fixture/bid-9602" } }),
    activity("bid_posted", "2026-09-25T09:00:00+09:00", "입찰공고 게시", { link: { label: "공고 원문", path: "https://www.g2b.go.kr/fixture/bid-9601" } }),
  ],
};

export const RECORD_FIXTURES: ReadonlyArray<RecordFixture> = [full, orderPlanOnly, preSpecOnly, bidPassed, noAuthority, merged, longFeed, rebid];

/** `GET /api/notices/{pk}` — 레코드가 읽는 필드(금액·계약방법·공동수급·마감·원문 주소)만 의미가 있다. */
export interface NoticeFixture {
  id: number;
  title: string;
  agency: string;
  estimated_price: number | null;
  budget: number | null;
  method: string | null;
  joint: string | null;
  deadline_at: string | null;
  url: string | null;
  source_type: "pre_spec" | "bid_notice";
}

export const NOTICE_FIXTURES: ReadonlyArray<NoticeFixture> = [
  { id: 9103, title: FULL_TITLE, agency: FULL_AGENCY, estimated_price: 1_230_000_000, budget: 1_450_000_000, method: "제한경쟁입찰", joint: "공동이행방식", deadline_at: BID_DEADLINE, url: EXTERNAL_BID_URL, source_type: "bid_notice" },
  { id: 9102, title: "클라우드 기반 통합정보시스템 구축 사전규격", agency: FULL_AGENCY, estimated_price: null, budget: null, method: null, joint: null, deadline_at: "2026-09-30T18:00:00+09:00", url: null, source_type: "pre_spec" },
  { id: 9202, title: "공공 데이터 품질관리 체계 구축 사전규격", agency: "산들군청", estimated_price: null, budget: 800_000_000, method: null, joint: null, deadline_at: "2026-10-18T18:00:00+09:00", url: null, source_type: "pre_spec" },
  { id: 9304, title: "정보보안 관제 용역", agency: "들판공단", estimated_price: 320_000_000, budget: null, method: "일반경쟁입찰", joint: null, deadline_at: "2026-10-10T18:00:00+09:00", url: null, source_type: "bid_notice" },
  { id: 9601, title: "통합 민원 포털 재구축", agency: "강변구청", estimated_price: 270_000_000, budget: 300_000_000, method: "일반경쟁입찰", joint: null, deadline_at: REBID_OLD_DEADLINE, url: "https://www.g2b.go.kr/fixture/bid-9601", source_type: "bid_notice" },
  { id: 9602, title: "통합 민원 포털 재구축 (재공고)", agency: "강변구청", estimated_price: 254_000_000, budget: 280_000_000, method: "협상에 의한 계약", joint: "분담이행방식", deadline_at: REBID_NEW_DEADLINE, url: "https://www.g2b.go.kr/fixture/bid-9602", source_type: "bid_notice" },
  { id: 9508, title: "장기 운영 데이터 이관 용역", agency: "언덕시청", estimated_price: 50_000, budget: null, method: "수의계약", joint: null, deadline_at: "2026-11-30T18:00:00+09:00", url: null, source_type: "bid_notice" },
];

/** `GET /api/notices/{pk}/related` — 입찰공고 9103의 비슷한 공고. */
export const RELATED_BY_NOTICE: Record<number, Array<{ relation: "ordinal" | "unified" | "pre_spec"; notice_pk: number; notice_key: string; title: string | null; grade: string | null; published_at: string | null; change_reason: string | null }>> = {
  9103: [
    { relation: "ordinal", notice_pk: 9111, notice_key: "20261014001-00", title: "클라우드 기반 통합정보시스템 구축 (재공고)", grade: null, published_at: "2026-10-13T09:00:00+09:00", change_reason: "마감일 연장" },
    { relation: "pre_spec", notice_pk: 9102, notice_key: "R26BK000001", title: "클라우드 기반 통합정보시스템 구축 사전규격", grade: null, published_at: "2026-09-20T09:00:00+09:00", change_reason: null },
  ],
  9102: [],
  9601: [
    { relation: "ordinal", notice_pk: 9690, notice_key: "20260925001-00", title: "옛 공고의 관련 공고", grade: null, published_at: "2026-09-25T09:00:00+09:00", change_reason: null },
  ],
  9602: [
    { relation: "ordinal", notice_pk: 9601, notice_key: "20260925001-00", title: "통합 민원 포털 재구축", grade: null, published_at: "2026-09-25T09:00:00+09:00", change_reason: "재공고" },
  ],
};

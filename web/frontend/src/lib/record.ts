import { daysUntil, deadlineDayLabel, DEADLINE_EMPHASIS_DAYS } from "./briefing";
import type {
  NoticeDetailResponse,
  OpportunityActivityItem,
  OpportunityActivityLink,
  OpportunityDetailResponse,
  OpportunityLinkView,
  OpportunityStageEntry,
  OpportunityStageState,
} from "./types";
import type { LifecycleStage } from "../components/opportunities/trackingFlow";

/*
 * 사업기회 레코드(`/opportunities/:id/*`)의 순수 도우미(RL-02 spec "레코드 헤더"·"좌측 정보").
 *
 * 서버가 준 연결·공고·활동만 이름 붙이고 모양을 바꾼다. 단계 상태·레코드 제목·판정은 만들지
 * 않는다(단계 바와 제목은 활동 응답이 준다). 값이 없으면 `미공개`·`미지정`으로 두고 0이나
 * 빈 값으로 접지 않는다.
 */

// ---------------------------------------------------------------------------
// 탭

export const RECORD_TABS = ["activity", "verdict", "proposal", "documents", "source", "similar"] as const;
export type RecordTab = (typeof RECORD_TABS)[number];

export const RECORD_TAB_LABEL: Record<RecordTab, string> = {
  activity: "활동",
  verdict: "판정",
  proposal: "제안서",
  documents: "서류",
  source: "원문",
  similar: "비슷한 공고",
};

export function parseRecordTab(value: string | undefined): RecordTab | null {
  return (RECORD_TABS as readonly string[]).includes(value ?? "") ? (value as RecordTab) : null;
}

/** 후속 기능이 채울 탭의 빈 상태 문장(spec "화면"). 판정 탭은 RL-03이 채웠으므로 여기에 없다. */
export const RECORD_TAB_EMPTY: Partial<Record<RecordTab, string>> = {
  proposal: "제안서 초안은 판정 뒤 만들 수 있습니다",
  documents: "제출 서류 체크는 준비 중입니다",
  source: "원문은 공고 상세에서 봅니다",
};

export const SIMILAR_EMPTY_NO_NOTICE = "공고가 연결되면 비슷한 공고를 찾습니다";

// ---------------------------------------------------------------------------
// 단계 바

/** 6단계 고정 순서의 라벨. 서버 응답의 `key`가 아니라 순서로 읽는다. */
export const STAGE_LABELS = ["발주계획", "사전규격", "입찰공고", "마감", "개찰", "계약"] as const;

export const STAGE_STATE_LABEL: Record<OpportunityStageState, string> = {
  done: "완료",
  current: "현재 단계",
  upcoming_deadline: "다가오는 마감",
  pending: "대기",
  unknown: "미확인",
};

export function stageLabelAt(index: number, entry: OpportunityStageEntry): string {
  return STAGE_LABELS[index] ?? entry.key;
}

// ---------------------------------------------------------------------------
// 연결에서 읽는 사실

/**
 * 단계별 대표 권위 연결. 대표는 **서버가 고른다**(활동 응답 `stages[].link_id`,
 * `opportunity_stages.representatives` — 연결 시각이 가장 늦은 것, 같으면 id가 큰 것). 화면은 그
 * 규칙을 다시 만들지 않고 id로 상세 `links`에서 찾기만 한다(business-rules "권위 연결의 정의를 그대로 쓴다").
 */
export type RepresentativeLinks = Record<LifecycleStage, OpportunityLinkView | null>;

/** `stages`의 고정 순서 앞 3칸(발주계획·사전규격·입찰공고). 화면은 `key`에 의미를 붙이지 않는다. */
const REPRESENTATIVE_STAGE_ORDER: readonly LifecycleStage[] = ["발주계획", "사전규격", "입찰공고"];

/**
 * 활동 응답 `stages[].link_id`를 상세 `links`에서 찾는다. 활동 응답이 아직 없거나(로딩·오류) 모양이
 * 맞지 않으면 `null`이고, 화면은 그동안 단계·마감 pill과 연결에서 오는 속성을 비워 둔다(추정하지 않는다).
 * `link_id`가 `null`이거나 그 id가 `links`에 없으면 그 단계 대표는 `null`이다.
 */
export function representativeLinks(
  links: readonly OpportunityLinkView[],
  stages: readonly OpportunityStageEntry[] | null | undefined,
): RepresentativeLinks | null {
  if (!stages || stages.length < REPRESENTATIVE_STAGE_ORDER.length) return null;
  const byId = new Map(links.map((link) => [link.id, link] as const));
  const resolved = {} as RepresentativeLinks;
  REPRESENTATIVE_STAGE_ORDER.forEach((stage, index) => {
    const id = stages[index]?.link_id;
    resolved[stage] = typeof id === "number" ? byId.get(id) ?? null : null;
  });
  return resolved;
}

export interface LatestAuthority {
  stage: LifecycleStage;
  link: OpportunityLinkView;
}

/** 대표 연결 중 가장 뒤 단계(입찰공고 > 사전규격 > 발주계획). 제목을 주는 연결과 같은 연결이다. */
export function latestAuthority(reps: RepresentativeLinks | null): LatestAuthority | null {
  if (!reps) return null;
  for (const stage of ["입찰공고", "사전규격", "발주계획"] as const) {
    const link = reps[stage];
    if (link) return { stage, link };
  }
  return null;
}

/** 공고(사전규격·입찰공고)를 가리키는 가장 뒤 단계의 대표 연결. 발주계획만 있거나 대표를 모르면 `null`이다. */
export function latestNoticeLink(reps: RepresentativeLinks | null): OpportunityLinkView | null {
  const latest = latestAuthority(reps);
  if (!latest || latest.stage === "발주계획" || latest.link.notice_id === null) return null;
  return latest.link;
}

// ---------------------------------------------------------------------------
// 헤더 pill (단계 · 마감 · 판정 · 추적 상태)

export type RecordPillTone = "stage" | "muted" | "warning" | "success" | "error";

export interface RecordPill {
  key: "stage" | "deadline" | "verdict" | "tracking";
  label: string;
  tone: RecordPillTone;
}

function deadlinePill(reps: RepresentativeLinks, now: Date): RecordPill | null {
  const bid = reps["입찰공고"];
  const preSpec = bid ? null : reps["사전규격"];
  const link = bid ?? preSpec;
  if (!link) return null;
  const prefix = bid ? "" : "의견 마감 ";
  const days = daysUntil(link.deadline_at, now);
  if (days === null) return { key: "deadline", label: bid ? "마감 미확인" : "의견 마감 미확인", tone: "muted" };
  if (days < 0) return { key: "deadline", label: bid ? "마감 지남" : "의견 마감 지남", tone: "muted" };
  return {
    key: "deadline",
    label: `${prefix}${deadlineDayLabel(days)}`,
    tone: days <= DEADLINE_EMPHASIS_DAYS ? "warning" : "muted",
  };
}

/**
 * 헤더 pill. `reps`가 `null`(활동 응답 로딩·오류)이면 단계·마감·판정 pill을 그리지 않고 추적 상태만
 * 보인다 — 대표 연결을 모르는 동안 다른 연결로 단계나 마감을 짐작하지 않는다.
 *
 * 판정 pill은 발주계획만 있으면 "연차 추적", 그 밖에는 서버 판정 view가 준 값(`verdict`: 판정 이름·
 * 분석 중·사람 검토 필요)이고, 값이 없으면(없음·불러오기 전·오류) "분석 대기"다(RL-03 spec).
 */
export function recordPills(
  item: OpportunityDetailResponse,
  reps: RepresentativeLinks | null,
  now: Date = new Date(),
  verdict: { label: string; tone: RecordPillTone } | null = null,
): RecordPill[] {
  const pills: RecordPill[] = [];
  if (reps) {
    const latest = latestAuthority(reps);
    const orderPlanOnly = latest?.stage === "발주계획";
    pills.push({ key: "stage", label: latest ? latest.stage : "단계 미확인", tone: latest ? "stage" : "muted" });
    const deadline = deadlinePill(reps, now);
    if (deadline) pills.push(deadline);
    pills.push(
      orderPlanOnly
        ? { key: "verdict", label: "연차 추적", tone: "muted" }
        : { key: "verdict", label: verdict?.label ?? "분석 대기", tone: verdict?.tone ?? "muted" },
    );
  }
  pills.push({
    key: "tracking",
    label: item.tracking_status,
    tone: item.tracking_status === "계속 추적" ? "success" : item.tracking_status === "보류" ? "warning" : "muted",
  });
  return pills;
}

// ---------------------------------------------------------------------------
// 금액·일시

/** `1,230,000,000` → `12억 3,000만원`. 억·만 단위로 읽되 반올림하지 않는다. */
export function formatKoreanAmount(value: number): string {
  if (!Number.isFinite(value) || value < 0) return "";
  const won = Math.round(value);
  if (won === 0) return "0원";
  const eok = Math.floor(won / 100_000_000);
  const man = Math.floor((won % 100_000_000) / 10_000);
  const rest = won % 10_000;
  const parts: string[] = [];
  if (eok > 0) parts.push(`${eok.toLocaleString("ko-KR")}억`);
  if (man > 0) parts.push(`${man.toLocaleString("ko-KR")}만`);
  if (rest > 0) parts.push(rest.toLocaleString("ko-KR"));
  return `${parts.join(" ")}원`;
}

const KST = "Asia/Seoul";
const kstParts = new Intl.DateTimeFormat("ko-KR", {
  timeZone: KST,
  year: "numeric",
  month: "numeric",
  day: "numeric",
  weekday: "short",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

interface KstMoment {
  year: number;
  month: number;
  day: number;
  weekday: string;
  hour: string;
  minute: string;
}

function kstMoment(value: Date): KstMoment {
  const map = new Map(kstParts.formatToParts(value).map((part) => [part.type, part.value] as const));
  return {
    year: Number(map.get("year")),
    month: Number(map.get("month")),
    day: Number(map.get("day")),
    weekday: map.get("weekday") ?? "",
    hour: map.get("hour") ?? "00",
    minute: map.get("minute") ?? "00",
  };
}

function parseInstant(value: string | null): Date | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/** `10월 20일 (화) 18:00`. 분까지만 적고 초는 쓰지 않는다. */
export function formatKstMinute(value: string | null): string | null {
  const parsed = parseInstant(value);
  if (!parsed) return null;
  const m = kstMoment(parsed);
  return `${m.month}월 ${m.day}일 (${m.weekday}) ${m.hour}:${m.minute}`;
}

/** 단계 바의 날짜 보조 줄: `10월 20일`. */
export function formatKstDay(value: string | null): string | null {
  const parsed = parseInstant(value);
  if (!parsed) return null;
  const m = kstMoment(parsed);
  return `${m.month}월 ${m.day}일`;
}

/**
 * 활동 항목의 시각. 오늘이면 `오늘 08:41`, 아니면 `10월 14일`(해가 다르면 연도를 앞에 붙인다).
 * 관측 시각은 회차 `generated_at`이라 초 단위를 노출하지 않는다.
 */
export function activityTimeLabel(at: string, now: Date = new Date()): string {
  const parsed = parseInstant(at);
  if (!parsed) return "시각 미확인";
  const m = kstMoment(parsed);
  const today = kstMoment(now);
  if (m.year === today.year && m.month === today.month && m.day === today.day) return `오늘 ${m.hour}:${m.minute}`;
  return m.year === today.year ? `${m.month}월 ${m.day}일` : `${m.year}년 ${m.month}월 ${m.day}일`;
}

/**
 * 활동 항목 `<time dateTime>` 값: KST 분 단위 `2026-10-14T08:41+09:00`. 초·마이크로초는 기계 판독
 * 속성에도 싣지 않는다(spec "초 단위 노출 금지"). 읽을 수 없으면 `null`이고 속성을 생략한다.
 */
export function activityDateTimeAttr(at: string): string | null {
  const parsed = parseInstant(at);
  if (!parsed) return null;
  const m = kstMoment(parsed);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${String(m.year).padStart(4, "0")}-${pad(m.month)}-${pad(m.day)}T${m.hour}:${m.minute}+09:00`;
}

/** 발주 예정월: `2027-03`·`03`·`3` 모두 `3월 발주 예정`. 읽을 수 없으면 `null`이다. */
export function plannedMonthText(month: string | null): string | null {
  const match = /^(?:\d{4}-)?(\d{1,2})$/.exec((month ?? "").trim());
  if (!match) return null;
  const value = Number(match[1]);
  return value >= 1 && value <= 12 ? `${value}월 발주 예정` : null;
}

// ---------------------------------------------------------------------------
// 좌측 속성 8개

export type AttributePlaceholder = "미공개" | "미지정";

export interface RecordAttribute {
  key: "agency" | "period" | "amount" | "method" | "joint" | "bid_deadline" | "owner" | "tracking";
  label: string;
  /** 값이 없으면 `null`이고 화면이 `placeholder`를 보조색으로 보인다. */
  value: string | null;
  /** 값 뒤의 보조 글자(금액이 추정가격인지 예산인지 등). */
  note?: string | null;
  placeholder: AttributePlaceholder;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function nonBlank(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

function jointMethodOf(notice: NoticeDetailResponse | null): string | null {
  const flags = asRecord(notice?.qualification_flags);
  const value = flags?.joint_contract_method;
  return typeof value === "string" ? nonBlank(value) : null;
}

/** 담당 = 마지막 반응·결정의 기록자. 활동 피드가 최신순이므로 처음 만나는 사람 항목이다. */
export function ownerFromActivity(items: readonly OpportunityActivityItem[]): string | null {
  for (const item of items) {
    if ((item.kind === "briefing_reacted" || item.kind === "tracking_decided") && nonBlank(item.actor)) {
      return item.actor?.trim() ?? null;
    }
  }
  return null;
}

export interface RecordAttributeInput {
  item: OpportunityDetailResponse;
  /** 서버 대표 연결. `null`(활동 응답 로딩·오류)이면 연결에서 오는 값은 모두 미공개다. */
  reps: RepresentativeLinks | null;
  notice: NoticeDetailResponse | null;
  activityItems: readonly OpportunityActivityItem[];
}

export function recordAttributes({ item, reps, notice, activityItems }: RecordAttributeInput): RecordAttribute[] {
  const latest = latestAuthority(reps);
  const orderPlanOnly = latest?.stage === "발주계획";
  const bid = reps?.["입찰공고"] ?? null;

  const agency = nonBlank(latest?.link.agency) ?? nonBlank(notice?.agency);

  let amount: number | null = null;
  let amountNote: string | null = null;
  if (orderPlanOnly) {
    amount = latest.link.budget;
    amountNote = amount === null ? null : "예산";
  } else if (notice) {
    if (notice.estimated_price !== null) {
      amount = notice.estimated_price;
      amountNote = "추정가격";
    } else if (notice.budget !== null) {
      amount = notice.budget;
      amountNote = "예산";
    }
  } else if (latest && latest.link.budget !== null) {
    amount = latest.link.budget;
    amountNote = "예산";
  }
  const amountText = amount === null ? null : formatKoreanAmount(amount) || null;

  const bidDeadline = bid ? formatKstMinute(bid.deadline_at ?? notice?.deadline_at ?? null) : null;
  const selectedBy = nonBlank(item.tracking_selected_by);
  const tracking = item.tracking_status === "미선택"
    ? "미선택"
    : selectedBy ? `${item.tracking_status} · ${selectedBy}` : item.tracking_status;

  return [
    { key: "agency", label: "발주기관", value: agency, placeholder: "미공개" },
    {
      key: "period",
      label: "사업기간",
      value: orderPlanOnly ? plannedMonthText(latest.link.planned_order_month) : null,
      placeholder: "미공개",
    },
    { key: "amount", label: "금액", value: amountText, note: amountText ? amountNote : null, placeholder: "미공개" },
    { key: "method", label: "계약방법", value: nonBlank(notice?.method), placeholder: "미공개" },
    { key: "joint", label: "공동수급", value: jointMethodOf(notice), placeholder: "미공개" },
    { key: "bid_deadline", label: "입찰 마감", value: bidDeadline, placeholder: "미공개" },
    { key: "owner", label: "담당", value: ownerFromActivity(activityItems) ?? selectedBy, placeholder: "미지정" },
    { key: "tracking", label: "추적", value: tracking, placeholder: "미공개" },
  ];
}

// ---------------------------------------------------------------------------
// 활동 피드

export type ActivityFilter = "all" | "people" | "business" | "action";

export const ACTIVITY_FILTER_LABEL: Record<ActivityFilter, string> = {
  all: "전체",
  people: "사람",
  business: "사업 사건",
  action: "다음 행동",
};

const PEOPLE_KINDS = new Set<string>([
  "tracking_decided",
  "link_reviewed",
  "briefing_reacted",
  "note_added",
  "action_added",
  "action_done",
]);

/** 사람 행동과 사업 사건의 구분(ui-spec §4.3). 신호 항목은 사람이 확인했을 때(기록자가 있을 때)만 사람 행동이다. */
export function activityGroup(item: OpportunityActivityItem): "people" | "business" {
  if (item.kind === "recheck_signal") return item.actor?.trim() ? "people" : "business";
  return PEOPLE_KINDS.has(item.kind) ? "people" : "business";
}

export function filterActivity(items: readonly OpportunityActivityItem[], filter: ActivityFilter): OpportunityActivityItem[] {
  if (filter === "all") return [...items];
  if (filter === "action") return items.filter((item) => item.kind === "action_added" || item.kind === "action_done");
  return items.filter((item) => activityGroup(item) === filter);
}

/** 이름의 첫 글자. 아바타에 쓰고 이름 전체는 title·접근성 이름에 둔다. */
export function initialOf(name: string | null | undefined): string {
  const first = Array.from((name ?? "").trim())[0];
  return first ?? "?";
}

export type SafeActivityLink =
  | { kind: "internal"; label: string; to: string }
  | { kind: "external"; label: string; href: string };

/** 같은 사이트 경로 또는 http(s) 주소만 연다. 그 밖의 값은 링크로 만들지 않는다. */
export function safeActivityLink(link: OpportunityActivityLink | null): SafeActivityLink | null {
  if (!link) return null;
  if (/^\/(?!\/)[^\s]*$/.test(link.path)) return { kind: "internal", label: link.label, to: link.path };
  try {
    const url = new URL(link.path);
    if (url.protocol === "http:" || url.protocol === "https:") return { kind: "external", label: link.label, href: url.toString() };
  } catch {
    // 주소로 읽을 수 없으면 링크를 만들지 않는다.
  }
  return null;
}

/**
 * 본문 앞에 기록자 이름(600)을 둔다. 결정·반응·완료처럼 서버 title이 이름으로 시작하면 그 이름을
 * 굵게 나누고, 노트·다음 행동은 title이 본문이라 이름이 없으므로 기록자 이름을 앞에 붙인다.
 */
export function splitActor(
  title: string,
  actor: string | null,
  kind: string,
): { lead: string | null; rest: string } {
  const name = actor?.trim();
  if (!name) return { lead: null, rest: title };
  if (kind === "note_added" || kind === "action_added") return { lead: name, rest: ` ${title}` };
  if (title.startsWith(name)) return { lead: name, rest: title.slice(name.length) };
  return { lead: null, rest: title };
}

// ---------------------------------------------------------------------------
// 다음 행동

const ACTION_PREFIX = "다음 행동: ";

export interface OpenAction {
  noteId: string;
  body: string;
  actor: string | null;
  detail: string | null;
  at: string;
}

function noteIdOf(itemId: string): string {
  const index = itemId.indexOf(":");
  return index < 0 ? itemId : itemId.slice(index + 1);
}

/** 완료 항목(`action_done`)이 없는 `action_added`만 남긴다. 입력은 최신순이다. */
export function openActions(items: readonly OpportunityActivityItem[]): OpenAction[] {
  const done = new Set(items.filter((item) => item.kind === "action_done").map((item) => noteIdOf(item.item_id)));
  return items
    .filter((item) => item.kind === "action_added" && !done.has(noteIdOf(item.item_id)))
    .map((item) => ({
      noteId: noteIdOf(item.item_id),
      body: item.title.startsWith(ACTION_PREFIX) ? item.title.slice(ACTION_PREFIX.length) : item.title,
      actor: item.actor,
      detail: item.detail,
      at: item.at,
    }));
}

/** 같은 입력은 같은 요청 식별자를 쓰기 위한 지문. 본문·담당·기록자·종류가 바뀌면 새 식별자다. */
export function noteFingerprint(kind: string, body: string, owner: string, actor: string): string {
  return JSON.stringify([kind, body, owner, actor]);
}

/*
 * 화면 정의. 값은 2026-11-23 운영 화면(127.0.0.1:18788)에서 본 공개 공고 정보를 본뜬 예시이고 담당자 이름은 가명이다.
 * 화면은 틀(Workspace·RecordView·DecisionView·OverviewView)에 내용만 넘긴다. 배치·부품 모양은 여기서 정하지 않는다.
 */
import type { ReactNode } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Claims, Facts, FillBlock, KeepOnly, Links, Para, StatusMark, type Decision, type FlowStep, type Mark } from "./kit";
import { Workspace, type Crumb, type Preview, type Row, type WorkspaceCfg } from "./templates";
import { DecisionView, OverviewView, RecordView, type DecisionCfg, type OverviewCfg, type RecordCfg } from "./templates2";

const need: Mark = { label: "결정 필요", tone: "warning" };
const tracking: Mark = { label: "계속 추적", tone: "accent" };
const unset: Mark = { label: "미선택", tone: "neutral" };
const done: Mark = { label: "개요 완료", tone: "success" };
const human: Mark = { label: "사람 검토 필요", tone: "warning" };
const undecided: Mark = { label: "미결정", tone: "neutral" };

const moveKeys = [{ keys: "up", label: "" }, { keys: "down", label: "행 이동" }];

/* ── 발주계획 ──────────────────────────────────────────────────────────── */

const orderPlanRows: Row[] = [
  ["2027년 원스톱관광플랫폼 낭만남해 운영대행 및 고도화 용역(협상에의한계약, 긴급)", "경상남도 남해군", "1.6억원", "11-22"],
  ["2027년 교통AI빅데이터 융합플랫폼 유지보수", "한국도로교통공단", "2.1억원", "11-21"],
  ["2027년 중구 홈페이지 통합 운영 및 클라우드 전환 용역(긴급)", "서울특별시 중구", "3.8억원", "11-21"],
  ["2027~2028년도 디지털연탄쿠폰시스템 유지보수용역", "한국광해광업공단", "6억원", "11-21"],
  ["2027년 역사 운영 통합정보시스템 유지관리 용역(협상에 의한 계약)", "남양주도시공사", "6,742만원", "11-21"],
  ["[긴급] 2027년 디지털기반 시설물 안전관리시스템 유지보수 용역", "서울특별시 서초구", "1.1억원", "11-21"],
  ["2027년 KLID 성과관리시스템 운영 및 유지관리", "한국지역정보개발원", "5,210.4만원", "11-21"],
  ["상환능력 예측모형 및 전산 개발 용역", "한국자산관리공사", "2.7억원", "11-21"],
  ["2027년 천안시 빅데이터 플랫폼 유지관리 및 AI 기반 분석 사업 용역", "충청남도 천안시", "3억원", "11-21"],
  ["성남문화재단 홈페이지 및 대관시스템 유지관리 용역", "재단법인 성남문화재단", "6,300만원", "11-21"],
].map(([title, agency, budget, seen], index) => ({
  id: `op-${index}`, title, agency, budget, meta: `${agency} · ${budget} · 첫 수집 ${seen}`,
  deadline: { text: "2026년 11월", level: "normal" as const }, group: index < 4 ? "이번 달 발주 예정 · 모델 관련" : "이번 달 발주 예정 · 첫 수집 11-21",
}));

const orderPlanDecision: Decision = {
  stateLabel: "추적 상태", state: need,
  actions: [
    { label: "넘기기", kind: "ghost" }, { label: "추적 종료", kind: "destructive" }, { label: "보류" }, { label: "추적 시작하기", kind: "primary" },
  ],
};

function orderPlanPreview(row: Row | null): Preview | null {
  if (!row) return null;
  return {
    eyebrow: `${row.agency} · 총괄기관 경상남도`, title: row.title, marks: [need, { label: "모델 · 관련", tone: "info" }], tags: ["신규(단기)"],
    idLine: "계획번호 R26DD20939612 · 첫 수집 11-22",
    facts: [
      { label: "발주계획 예산", value: "160,000,000원", strong: true }, { label: "발주 예정", value: "2026년 11월", strong: true },
      { label: "사업 분야", value: "일반용역" }, { label: "계약방법", value: "제한경쟁" },
      { label: "조달방식", value: "자체조달" }, { label: "공고 게시", value: "아직 없음" },
    ],
    flow: { active: 0, steps: [{ label: "발주계획", description: "수집 11-22" }, { label: "사전규격", description: "아직 없음" }, { label: "입찰공고", description: "아직 없음" }, { label: "최종 Go/No-Go", description: "결정 없음" }] },
    sections: [{
      id: "reason", title: "모델이 관련으로 본 이유",
      body: (
        <FillBlock>
          <Para>사업명 '원스톱관광플랫폼 낭만남해 운영대행 및 고도화'가 public-si-lifecycle의 플랫폼 고도화·운영 역량과 직접 맞닿습니다.</Para>
          <Facts side facts={[{ label: "근거 위치", value: "발주계획 사업명" }, { label: "가까운 역량", value: "public-si-lifecycle" }]} />
        </FillBlock>
      ),
    }],
    link: "사업 추적에서 보기",
    decision: orderPlanDecision,
  };
}

const orderPlans: WorkspaceCfg = {
  kind: "review",
  views: [{ id: "related", label: "관련", count: "829" }, { id: "unsure", label: "불확실", count: "783" }, { id: "unjudged", label: "모델 미판정", count: "4,097" }, { id: "all", label: "전체", count: "9,620" }],
  view: "related", filters: ["추적 미결정", "발주 예정 11월"], searchLabel: "사업명·발주기관·계획번호",
  listTitle: "관련 829건", listNote: "추적을 정하지 않은 건",
  mainHeader: "사업명 / 발주기관", statusHeader: "상태", deadlineHeader: "발주 예정",
  bulk: [{ label: "추적 종료", kind: "ghost" }, { label: "일괄 추적 시작" }],
  rows: orderPlanRows, total: 829, pageSize: 100,
  groups: ["이번 달 발주 예정 · 모델 관련", "이번 달 발주 예정 · 첫 수집 11-21"],
  preview: orderPlanPreview, previewTabs: ["요약", "모델 근거", "사업 흐름"], position: true,
  shortcuts: [...moveKeys, { keys: "mod+enter", label: "추적 시작" }],
};

/* ── 사전규격 ──────────────────────────────────────────────────────────── */

const preSpecRows: Row[] = [
  ["2027년 구리시 홈페이지 운영 및 유지관리 용역", "경기도 구리시", "2억원", human],
  ["2027년 평택시문화재단 홈페이지 유지관리 용역", "재단법인 평택시문화재단", "9,699.8만원", done],
  ["2027년~2029년도 특정수질유해물질 배출량조사 시스템 유지관리(장기계속 1차)", "기후에너지환경부 국립환경과학원", "3억원", done],
  ["화성시 자율주행 시범서비스 구축·운영 용역", "경기도 화성시", "17.8억원", done],
  ["강원후평 스마트그린산업단지 통합관제센터 화재감시 및 통합관제 S/W 구축용역", "아이씨티웨이주식회사", "8.1억원", done],
  ["2027~2028 충청북도교육도서관 정보시스템 통합 유지관리 용역", "충청북도교육청", "4.9억원", done],
  ["(수소배관망) 수소배관 건전성 진단 및 통합모니터링 시스템 구축 용역", "(주)한국가스기술공사", "2.2억원", done],
  ["2027년 한국의약품안전관리원 정보시스템 통합 운영관리", "한국의약품안전관리원", "10.1억원", human],
  ["2027년 범죄위험도 예측분석 시스템 유지관리 사업", "경찰청", "1.7억원", done],
  ["2027년 청년인재DB 시스템 관리 용역", "국무조정실", "3.1억원", done],
].map(([title, agency, budget, mark], index) => ({
  id: `ps-${index}`, title: title as string, agency: agency as string, budget: budget as string,
  meta: `${agency as string} · ${budget as string} · 독립 발견`, mark: mark as Mark,
  deadline: index < 8 ? { text: "오늘 23:59", level: "urgent" as const } : index === 8 ? { text: "D-2 · 11.25", level: "soon" as const } : { text: "D-4 · 11.27", level: "normal" as const },
  group: index < 8 ? "오늘 의견 마감" : "이번 주 마감",
}));

function preSpecPreview(row: Row | null): Preview | null {
  if (!row) return null;
  return {
    eyebrow: `수요기관 ${row.agency} · 공고기관 조달청 서울지방조달청`, title: row.title, marks: [row.mark ?? done, unset],
    tags: ["독립 발견", "일반용역", "SW사업대상 Y"], idLine: "사전규격 R26BD00302060 · 게시 11.18 06:49",
    facts: [
      { label: "사업 예산", value: "196,971,200원", strong: true }, { label: "의견등록 마감", value: "11.23 23:59 · 오늘", strong: true },
      { label: "게시", value: "11.18 06:49" }, { label: "본공고", value: "미확인" },
    ],
    flow: { active: 1, steps: [{ label: "발주계획", description: "연결 없음", state: "unknown" }, { label: "사전규격", description: "의견 마감 오늘", state: "current", status: "warning" }, { label: "입찰공고", description: "아직 없음" }, { label: "최종 Go/No-Go", description: "결정 없음" }] },
    sections: [{
      id: "overview", title: "개요 검토", aside: <StatusMark mark={row.mark ?? done} />,
      body: <FillBlock><Para>입력 범위 또는 실행 결과를 사람이 확인해야 하므로 검증된 권고로 확정할 수 없어요.</Para></FillBlock>,
    }],
    link: "원문·첨부 보기",
    decision: {
      stateLabel: "추적 상태", state: unset,
      actions: [{ label: "검토 제외", kind: "ghost" }, { label: "상세 페이지 열기" }, { label: "추적 시작하기", kind: "primary" }],
    },
  };
}

const preSpecs: WorkspaceCfg = {
  kind: "review",
  views: [{ id: "review", label: "검토할 항목", count: "88" }, { id: "check", label: "확인 필요", count: "36" }, { id: "recent", label: "최근 수집", count: "862" }, { id: "tracking", label: "추적 중", count: "7" }, { id: "all", label: "전체 이력", count: "1,264" }],
  view: "review", filters: ["마감 전", "개요 완료·사람 검토 필요"], searchLabel: "사업명·기관명 검색",
  listTitle: "검토할 항목 88건", listNote: "마감 임박순",
  mainHeader: "사업명 / 발주기관", statusHeader: "개요 상태", deadlineHeader: "의견 마감",
  bulk: [{ label: "검토 제외", kind: "ghost" }, { label: "선택 검토" }, { label: "일괄 추적 시작" }],
  rows: preSpecRows, total: 88, pageSize: 100, groups: ["오늘 의견 마감", "이번 주 마감"],
  preview: preSpecPreview, previewTabs: ["요약", "개요", "원문·첨부"], position: true,
  shortcuts: [...moveKeys, { keys: "mod+enter", label: "상세 열기" }],
};

/* ── 사업기회 ──────────────────────────────────────────────────────────── */

const opportunityFlow = { active: 2, current: true, steps: [
  { label: "발주계획", description: "연결 미확인", state: "unknown" as const }, { label: "사전규격", description: "연결 미확인", state: "unknown" as const },
  { label: "입찰공고", description: "공식 연결 · 11.21", state: "done" as const }, { label: "최종 Go/No-Go", description: "결정 없음", state: "todo" as const },
] };

const opportunityRows: Row[] = [
  ["2027 서초 빅데이터 플랫폼 유지보수 용역", "서울특별시 서초구", "2.4억원", "사전규격", { text: "내일 마감", level: "urgent" as const }],
  ["2027년 용인시 행정정보 운영시스템 통합유지관리 용역", "경기도 용인시", "2.5억원", "입찰공고", { text: "D-2 · 11.25", level: "urgent" as const }],
  ["2027년 지적정보시스템 통합 유지관리 용역", "경기도 수원시", "1.9억원", "입찰공고", { text: "D-3 · 11.26", level: "soon" as const }],
  ["2027년 스마트도시통합센터 정보시스템 통합유지보수 용역", "경기도 안양시", "19.4억원", "입찰공고", { text: "D-9 · 12.02", level: "normal" as const }],
  ["2027년 원스톱관광플랫폼 낭만남해 운영대행 및 고도화 용역", "경상남도 남해군", "1.6억원", "발주계획", { text: "마감 없음", level: "none" as const }],
  ["2027년 청년인재DB 시스템 관리 용역", "국무조정실", "3.1억원", "사전규격", { text: "D-4 · 11.27", level: "normal" as const }],
].map(([title, agency, budget, stage, deadline], index) => ({
  id: `opp-${index}`, title: title as string, agency: agency as string, budget: budget as string,
  meta: `${agency as string} · ${budget as string} · 현재 단계 ${stage as string}`, mark: tracking,
  deadline: deadline as Row["deadline"], group: index < 3 ? "7일 안 마감" : "그 밖의 추적 중",
}));

function opportunityPreview(row: Row | null): Preview | null {
  if (!row) return null;
  return {
    eyebrow: `발주기관 ${row.agency}`, title: row.title, marks: [tracking], idLine: "사업 #11866 · 입찰공고에서 처음 등장",
    facts: [
      { label: "현재 단계", value: "입찰공고", strong: true }, { label: "입찰 마감", value: "12월 2일 (수) 10:00", strong: true },
      { label: "금액", value: "19억 4,121만 3,636원 · 추정가격" }, { label: "최종 Go/No-Go", value: "결정 없음" },
    ],
    flow: opportunityFlow,
    sections: [
      { id: "links", title: "연결된 공고", aside: "후보·검색 기록 포함 2건", body: (
        <Facts side facts={[
          { label: "사전규격", value: "제목 미확인 · R26BD00289669 · 공식 연결" },
          { label: "입찰공고", value: "2027년 스마트도시통합센터 정보시스템 통합유지보수 용역 · R26BK01844973-000 · 공식 연결" },
        ]} />
      ) },
      { id: "check", title: "확인 사항", body: <Para dim>열린 확인 항목이 없어요. 체크는 연결 확정이고 분석 완료·입찰 참여 승인은 별도예요.</Para> },
    ],
    link: "레코드 열기",
    decision: {
      stateLabel: "추적 상태", state: tracking, note: "김담당 · 11.21 21:11",
      actions: [{ label: "추적 상태 변경" }, { label: "연결 공고 보기", kind: "primary" }],
    },
  };
}

const opportunities: WorkspaceCfg = {
  kind: "review",
  views: [{ id: "action", label: "조치 필요", count: "0" }, { id: "tracking", label: "추적 중", count: "9" }, { id: "hold", label: "보류", count: "0" }, { id: "due", label: "마감 임박" }, { id: "ended", label: "추적 종료", count: "0" }, { id: "new", label: "신규 입찰공고", count: "1,359" }, { id: "all", label: "전체", count: "12,022" }],
  view: "tracking", filters: ["추적 중"], searchLabel: "사업명·발주기관 검색",
  listTitle: "사업 추적 목록 · 9건", listNote: "마감 임박순",
  mainHeader: "사업명 / 발주기관", statusHeader: "추적 상태", deadlineHeader: "다음 마감",
  rows: opportunityRows, total: 9, pageSize: 100, groups: ["7일 안 마감", "그 밖의 추적 중"],
  preview: opportunityPreview, previewTabs: ["사업 흐름", "확인 사항", "추적 이력"], shortcuts: moveKeys,
};

/* ── 최종 Go/No-Go ─────────────────────────────────────────────────────── */

const goNoGoRows: Row[] = [
  { id: "gng-0", title: "2027년 용인시 행정정보 운영시스템 통합유지관리 용역", agency: "경기도 용인시", budget: "2.5억원", meta: "경기도 용인시 · 추정가격 253,745,455원 · 사업기회 1843", note: "변경 비교 결과 없음", mark: undecided, deadline: { text: "D-2 · 11.25", level: "urgent" }, group: "7일 안 입찰 마감" },
  { id: "gng-1", title: "2027년 스마트도시통합센터 정보시스템 통합유지보수 용역", agency: "경기도 안양시", budget: "19.4억원", meta: "경기도 안양시 · 추정가격 1,941,213,636원 · 사업기회 11866", note: "변경 비교 결과 없음", mark: undecided, deadline: { text: "D-9 · 12.02", level: "normal" }, group: "그 뒤 마감" },
];

const conditionFacts = [
  { label: "입찰 마감", value: "11월 25일 10:00 · D-2", strong: true }, { label: "추정가격", value: "253,745,455원", strong: true },
  { label: "최신 공고", value: "R26BK01829671 · 차수 000" }, { label: "계약방법", value: "일반경쟁" },
];

const goNoGo: WorkspaceCfg = {
  kind: "review",
  views: [{ id: "target", label: "검토 대상", count: "2" }, { id: "recheck", label: "재검토", count: "0" }, { id: "confirm", label: "공고 확인 필요", count: "0" }, { id: "log", label: "결정 기록", count: "1" }, { id: "all", label: "전체", count: "9" }],
  view: "target", searchLabel: "사업명·발주기관 검색",
  listTitle: "최종 결정 목록 · 2건", listNote: "입찰 마감순",
  mainHeader: "사업명 / 발주기관", statusHeader: "사람 결정", deadlineHeader: "입찰 마감",
  rows: goNoGoRows, total: 2, pageSize: 100, groups: ["7일 안 입찰 마감", "그 뒤 마감"],
  preview: (row) => (row ? {
    eyebrow: `발주기관 ${row.agency}`, title: row.title, marks: [undecided], idLine: "사업기회 1843 · 계속 추적 · 입찰공고 R26BK01829671-000",
    facts: conditionFacts,
    sections: [{ id: "delta", title: "직전 차수 변경", body: <Para dim>비교할 직전 차수가 없어요.</Para> }],
    decision: { stateLabel: "현재 사람 결정", state: undecided, actions: [{ label: "공고 조건 검토·결정 열기", kind: "primary" }] },
  } : null),
  previewTabs: ["검토 요약", "비교 문서", "결정 기록"], shortcuts: moveKeys,
};

/* ── 브리핑 ────────────────────────────────────────────────────────────── */

const briefing: WorkspaceCfg = {
  kind: "review",
  views: [{ id: "today", label: "오늘 추천", count: "6" }, { id: "reacted", label: "반응한 항목", count: "2" }], view: "today",
  listTitle: "오늘 추천 6건", listNote: "브리핑 11.23 07:10 발송분",
  mainHeader: "사업명 / 발주기관", statusHeader: "반응", deadlineHeader: "마감",
  rows: preSpecRows.slice(0, 6).map((row, index) => ({ ...row, id: `br-${index}`, mark: index < 2 ? { label: "관심", tone: "accent" as const } : { label: "반응 없음", tone: "neutral" as const }, group: index < 2 ? "반응한 항목" : "아직 보지 않은 추천" })),
  total: 6, pageSize: 100, groups: ["반응한 항목", "아직 보지 않은 추천"],
  preview: (row) => {
    const base = preSpecPreview(row);
    return base ? { ...base, decision: { stateLabel: "추적 상태", state: unset, actions: [{ label: "관심 없음", kind: "ghost" }, { label: "상세 페이지 열기" }, { label: "추적 시작하기", kind: "primary" }] } } : null;
  },
  previewTabs: ["요약", "개요", "원문·첨부"],
};

/* ── 관리: 판정 기준 · 실행 상태 · 회사 근거 ───────────────────────────── */

const gateFacts = [
  { label: "recall", value: "96.3% · 기준 90% 이상", strong: true }, { label: "precision", value: "45.6% · 기준 35% 이상", strong: true },
  { label: "중요 누락", value: "0건 · 기준 3건 이하" }, { label: "하루 검토량", value: "59건 · 기준 80건 이하" },
];

const criteria: WorkspaceCfg = {
  kind: "admin",
  views: [{ id: "c2", label: "발주계획 선별 (C-2)" }, { id: "c1", label: "공고 판정 (C-1)" }], view: "c2",
  sideNav: [
    { title: "발주계획 선별 (C-2)", items: [{ label: "선별 정책", active: true }] },
    { title: "공고 판정 (C-1)", items: [{ label: "판정용 프로필 사본" }, { label: "판정 정책" }, { label: "품질 게이트" }, { label: "회차 검증 지표" }] },
  ],
  strip: [{ label: "운영 활성", value: "c2-order-plan-screening-v6" }, { label: "일일 자동 실행", value: "켜짐 · 11.19 01:40" }, { label: "최근 기준일", value: "11-22 · C-2 성공" }, { label: "서버 blocker", value: "없음" }],
  listTitle: "발주계획 선별 정책", listNote: "2건",
  mainHeader: "정책 버전", statusHeader: "상태",
  rows: [
    { id: "v6", title: "c2-order-plan-screening-v6", agency: "policy 57366b04f952", meta: "policy 57366b04f952 · binding ad583ce21ba8", note: "활성화 2026.11.19 01:40 · jechoi", mark: { label: "운영 활성", tone: "success" }, group: "운영 중" },
    { id: "v5", title: "c2-order-plan-screening-v5", agency: "policy 1e6d4ef1414c", meta: "policy 1e6d4ef1414c · binding 2e77505efd6a", note: "활성화 이력 2026.10.14 21:59 · jechoi", mark: { label: "교체됨", tone: "neutral" }, group: "교체된 버전" },
  ],
  total: 2, pageSize: 100, groups: ["운영 중", "교체된 버전"], listFoot: "policy는 적재 CLI가 만들어요 · 활성 여부의 정본은 DB 행",
  preview: (row) => (row ? {
    eyebrow: "발주계획 선별 정책", title: row.title, marks: [row.mark!], idLine: `${row.agency} · 적재 2026.11.19 00:55 · jechoi`,
    facts: gateFacts,
    sections: [
      { id: "daily", title: "일일 자동 실행", aside: <StatusMark mark={{ label: "자동 실행 켜짐", tone: "success" }} />, body: <Para dim>일일 스크립트가 실행되면 이 버전으로 판정해요. policy를 교체하면 자동 실행이 멈춰요.</Para> },
      { id: "gate", title: "게이트 결과", aside: <StatusMark mark={{ label: "통과", tone: "success" }} />, body: <FillBlock><Para>두 pass 모두 네 지표를 충족했어요. 이 평가의 artifact digest로 활성화를 요청할 수 있어요.</Para></FillBlock> },
    ],
    decision: { stateLabel: "운영 상태", state: row.mark!, note: "교체는 새 버전 활성화로", actions: [{ label: "일일 자동 실행 끄기" }, { label: "새 버전 활성화", kind: "primary", disabled: true }] },
  } : null),
  previewTabs: ["요약", "게이트 결과", "실행 이력"],
};

const noRun: Mark = { label: "판정 실행 없음", tone: "neutral" };
const runStatus: WorkspaceCfg = {
  kind: "admin",
  views: [{ id: "runs", label: "수집 실행" }, { id: "attachments", label: "첨부 확보" }, { id: "always", label: "상시 운영" }, { id: "audit", label: "산출물 감사 로그" }], view: "runs",
  subViews: [{ id: "all", label: "전체", count: "57" }, { id: "running", label: "실행 중", count: "0" }, { id: "check", label: "확인 필요", count: "0" }],
  sideNav: [{ title: "실행 상태", items: [{ label: "수집 실행", active: true }, { label: "첨부 확보" }, { label: "상시 운영" }, { label: "산출물 감사 로그" }] }],
  strip: [{ label: "공고 판정 스케줄러", value: "꺼짐 · 환경 차단" }, { label: "현재 실행", value: "0건" }, { label: "조회 범위", value: "최근 0건 / 전체 0건" }, { label: "마지막 성공 조회", value: "오후 7:21" }],
  searchLabel: "회차·기간 검색",
  listTitle: "실행 회차 목록", listNote: "57건",
  mainHeader: "회차", statusHeader: "판정 실행",
  rows: [
    ["발주계획 회차 · 2026-11-22 ~ 11-23", "발주계획", "11.23 07:00 · 수집 값 없음 · 회차 완료"],
    ["공고 판정 회차 · 2026-11-19 ~ 11-22", "공고", "11.23 06:30 · 수집 2,741 · 회차 완료"],
    ["발주계획 회차 · 2026-11-21 ~ 11-22", "발주계획", "11.22 07:00 · 수집 값 없음 · 회차 완료"],
    ["공고 판정 회차 · 2026-11-18 ~ 11-21", "공고", "11.22 06:30 · 수집 4,147 · 회차 완료"],
    ["발주계획 회차 · 2026-11-20 ~ 11-21", "발주계획", "11.21 07:00 · 수집 값 없음 · 회차 완료"],
  ].map(([title, agency, meta], index) => ({ id: `run-${index}`, title, agency, meta, mark: noRun, group: index < 2 ? "오늘 수집한 회차" : "이전 회차" })),
  total: 57, pageSize: 20, groups: ["오늘 수집한 회차", "이전 회차"],
  preview: (row) => (row ? {
    eyebrow: "선택한 회차 · 2026-11-22 ~ 2026-11-23", title: row.title, marks: [noRun, { label: "품질 표식 없음", tone: "neutral" }],
    idLine: "lifecycle-20261122-plans--20261122T220002.274481Z · 생성 11.23 07:00",
    facts: [{ label: "수집·정규화", value: "대기 · 수집 값 없음" }, { label: "표본 선정", value: "대기 · 표본 0건" }, { label: "공고 판정", value: "대기 · 판정 0건" }, { label: "보고 생성", value: "대기" }],
    flow: { active: 0, current: true, steps: [{ label: "수집·정규화", description: "대기", state: "todo" }, { label: "표본 선정", description: "대기", state: "todo" }, { label: "공고 판정", description: "대기", state: "todo" }, { label: "보고 생성", description: "대기", state: "todo" }] },
    sections: [{ id: "full", title: "전체 후보 판정 실행", aside: "실행 기록 없음", body: <FillBlock><Para>이 회차에는 조회 범위 안의 전량 판정 실행이 없어요. 없음을 실행 0건이나 성공으로 읽지 않아요.</Para></FillBlock> }],
    link: "이 회차의 발주계획 보기",
    decision: { stateLabel: "판정 실행", state: noRun, actions: [{ label: "파이프라인 실행" }, { label: "전량 판정 등록", kind: "primary" }] },
  } : null),
  previewTabs: ["진행 현황", "실행 기록", "실행 기준"],
};

const unknown: Mark = { label: "미확인", tone: "neutral" };
const company: WorkspaceCfg = {
  kind: "admin",
  views: [{ id: "check", label: "확인 필요", count: "4" }, { id: "license", label: "자격" }, { id: "record", label: "실적" }, { id: "people", label: "인력" }, { id: "preference", label: "선호" }], view: "check",
  sideNav: [{ title: "회사 근거", items: [{ label: "확인 필요", active: true }, { label: "자격" }, { label: "실적" }, { label: "인력" }, { label: "선호" }] }],
  strip: [{ label: "회사 근거", value: "예시 · 운영은 미등록" }, { label: "마지막 저장", value: "값 없음" }, { label: "확인 필요", value: "4건" }, { label: "편집", value: "읽기 전용" }],
  listTitle: "확인 필요 항목", listNote: "4건 · 예시",
  mainHeader: "항목", statusHeader: "확인 상태",
  rows: [
    ["소프트웨어사업자 신고", "자격", "출처 회사소개서 · 유효기간 미확인"],
    ["직접생산확인 증명", "자격", "출처 없음 · 보유 여부 미확인"],
    ["최근 3년 공공 SI 실적", "실적", "출처 홈페이지 · 계약 금액 미확인"],
    ["정보처리기사 보유 인력 수", "인력", "출처 없음 · 값 없음"],
  ].map(([title, agency, meta], index) => ({ id: `co-${index}`, title, agency, meta, mark: unknown, group: agency })),
  total: 4, pageSize: 100, groups: ["자격", "실적", "인력"],
  preview: (row) => (row ? {
    eyebrow: `회사 근거 · ${row.agency}`, title: row.title, marks: [unknown], idLine: "예시 화면이에요. 운영 회사 근거는 아직 등록되지 않았어요.",
    facts: [{ label: "값", value: "미확인" }, { label: "출처", value: row.meta.split(" · ")[0].replace("출처 ", "") }, { label: "유효기간", value: "미확인" }, { label: "마지막 확인", value: "값 없음" }],
    sections: [{ id: "use", title: "이 항목을 쓰는 판정", body: <Para dim>미확인 값은 추정하지 않고 검증 대기로 남겨요. 판정에는 "확인 요청"으로 표시돼요.</Para> }],
  } : null),
  previewTabs: ["요약", "출처", "변경 이력"],
};

/* ── 읽기 상세: 사전규격 상세 · 사업기회 레코드 · 입찰공고 상세 ─────────── */

const preSpecDetail: RecordCfg = {
  current: "single",
  eyebrow: "사전규격 · 국무조정실", title: "2027년 청년인재DB 시스템 관리 용역", marks: [unset], tags: ["일반용역", "SW사업대상 Y", "독립 발견"],
  facts: [
    { label: "의견 마감", value: "2026.11.27 23:59 KST · D-4", strong: true }, { label: "사업 예산", value: "307,628,000원", strong: true },
    { label: "게시", value: "2026.11.22 15:05 KST" }, { label: "본공고", value: "미확인" },
  ],
  idLine: "사전규격번호 R26BD00304456 · 공고기관 조달청",
  flow: { active: 1, steps: [{ label: "발주계획", description: "연결 없음", state: "unknown" }, { label: "사전규격", description: "의견 마감 D-4", state: "current" }, { label: "입찰공고", description: "아직 없음" }, { label: "최종 Go/No-Go", description: "결정 없음" }] },
  sections: [
    { id: "overview", title: "사업 개요와 주요 과업", aside: <a className="mk-link" href="#">전체 근거 PDF 열기 ↗</a>, body: (
      <>
        <div className="mk-inline-marks"><StatusMark mark={{ label: "사람 확인 필요 · 사유 6건", tone: "warning" }} /><StatusMark mark={{ label: "참조 실행 · 품질 미측정", tone: "neutral" }} /></div>
        <Para dim>변환 PDF 71쪽 중 3~5쪽을 읽은 요약이에요. 판정이 아니에요.</Para>
        <Claims items={[
          { text: "사업명은 청년인재DB 시스템 관리 용역이다.", page: "PDF 3페이지" },
          { text: "사업은 정책결정 과정에 참여를 희망하는 청년과 정책담당자를 이어주는 청년인재 데이터베이스 관리 및 시스템의 안정적 운영과 고도화를 목적으로 한다.", page: "PDF 3페이지" },
          { text: "소요예산은 305,000천원(잠정, 부가가치세 포함)이다.", page: "PDF 3페이지" },
        ]} />
      </>
    ) },
    { id: "tasks", title: "주요 과업", body: <Para dim>이번 입력 범위에는 없음</Para> },
    { id: "source", title: "원문·첨부", aside: "첨부 1건 · 변환 완료", body: <Facts side facts={[{ label: "제안요청서", value: "제안요청서(청년인재DB).hwp · PDF 71쪽" }, { label: "나라장터", value: "사전규격 원문 열기 ↗" }]} /> },
    { id: "process", title: "처리 상태·기술 정보", aside: "문제 없음 · 접힘", body: <Para dim>자동 준비 단계 · 문서 준비 · 처리 이력 · 꺼진 기능 안내(RL 분석·회사 적합성)</Para> },
  ],
  decision: { stateLabel: "추적 상태", state: unset, hint: "분석 전에는 추적 시작만 정해요.", actions: [{ label: "추적 시작하기", kind: "primary" }] },
  decisionCurrent: true,
};

const recordFacts = [
  { label: "단계", value: "입찰공고", strong: true }, { label: "입찰 마감", value: "12월 2일 (수) 10:00 · D-9", strong: true },
  { label: "금액", value: "19억 4,121만 3,636원 · 추정가격" }, { label: "최종 Go/No-Go", value: "결정 없음" },
];

const opportunityRecord: RecordCfg = {
  current: "rail",
  eyebrow: "사업기회 #11866 · 경기도 안양시", title: "2027년 스마트도시통합센터 정보시스템 통합유지보수 용역", marks: [tracking],
  summary: "입찰공고까지 연결했어요.", facts: recordFacts,
  railFacts: [{ label: "계약방법", value: "일반경쟁" }, { label: "공동수급", value: "(전자)공동이행" }, { label: "사업기간", value: "미공개" }, { label: "담당", value: "김담당" }],
  tabs: { items: ["활동", "판정", "제안서", "서류", "원문", "비슷한 공고"], active: "활동" },
  flow: { active: 2, current: true, steps: [
    { label: "발주계획", description: "미확인", state: "unknown" }, { label: "사전규격", description: "미확인", state: "unknown" },
    { label: "입찰공고", description: "공식 연결 · 11월 21일 · R26BK01844973-000", state: "done" },
    { label: "마감·개찰", description: "12월 2일", state: "current", status: "warning" }, { label: "계약", description: "미확인", state: "todo" },
    { label: "최종 Go/No-Go", description: "결정 없음 · 입찰 참여는 사람이 따로 정해요.", state: "todo" },
  ] },
  sections: [
    { id: "activity", title: "활동", body: <FillBlock><Para dim>노트 남기기… (TextArea · 저장은 담당자 이름이 있어야 해요)</Para></FillBlock> },
    { id: "judgment", title: "참여 판정", aside: <StatusMark mark={{ label: "이 환경에서 꺼져 있음", tone: "neutral" }} />, body: <Para dim>참여 판정(RL 분석)이 꺼져 있어 판정을 요청하거나 볼 수 없어요. 추적 결정과 최종 Go/No-Go는 판정 없이도 사람이 정해요.</Para> },
  ],
  rail: [
    { id: "tracking", title: "추적 상태", body: <><Para>11월 21일에 추적을 시작했어요.</Para><Para dim>김담당 · 사유: 사업 범위가 맞아 후속 공고 확인</Para><KeepOnly><Links items={["추적 상태 바꾸기"]} /></KeepOnly></> },
    { id: "shortcuts", title: "검토 바로가기", body: <Links items={["입찰공고 원문 보기", "공고 조건 검토·결정", "확인 항목 답변"]} /> },
  ],
  decision: { stateLabel: "추적 상태", state: tracking, note: "김담당 · 11.21 21:11", actions: [{ label: "추적 상태 바꾸기" }, { label: "공고 조건 검토·결정", kind: "primary" }] },
};

const noticeDetail: RecordCfg = {
  current: "single",
  eyebrow: "입찰공고 · 경기도 안양시", title: "2027년 스마트도시통합센터 정보시스템 통합유지보수 용역",
  marks: [{ label: "등급 미확인", tone: "neutral" }, { label: "준비 상태 미확인", tone: "neutral" }], tags: ["회차 11-19~11-22"],
  facts: [
    { label: "입찰 마감", value: "12월 2일 (수) 10:00 · D-9", strong: true }, { label: "추정가격", value: "1,941,213,636원", strong: true },
    { label: "판정 등급", value: "판정 없음 · 등급 출처 없음" }, { label: "다음 행동 안내", value: "미확인" },
  ],
  idLine: "bid:R26BK01844973-000 · 조달청 · 실행 회차 11-19~11-22 수집",
  flow: { active: 2, current: true, steps: [{ label: "사전규격", description: "본문 미수집", state: "unknown" }, { label: "본공고", description: "11.22 15:05", state: "done" }, { label: "정정", description: "11.22 15:05", state: "done" }, { label: "판정", description: "미진행", state: "todo" }, { label: "마감", description: "12.02", state: "todo" }] },
  sections: [
    { id: "summary", title: "판정 요약", body: <Facts columns={4} facts={[{ label: "종합 권고", value: "없음" }, { label: "확인 항목", value: "0" }, { label: "차단 항목", value: "0" }, { label: "반론", value: "0" }]} /> },
    { id: "info", title: "공고 정보", aside: "나라장터 제공 값", body: <Facts columns={4} facts={[{ label: "계약방법", value: "일반경쟁" }, { label: "낙찰방법", value: "협상에의한계약" }, { label: "공동수급", value: "(전자)공동이행" }, { label: "업종제한", value: "Y · 제한 있음" }]} /> },
    { id: "flags", title: "자격·제약 플래그", aside: "나라장터 제공 값", body: <Facts columns={4} facts={[{ label: "참가제한", value: "N · 제한 없음" }, { label: "1468 업종 표시", value: "Y" }, { label: "지역제한 근거", value: "값 없음" }, { label: "재공고", value: "Y · 재공고" }]} /> },
  ],
};

/* ── 입찰 참여 결정 ────────────────────────────────────────────────────── */

const bidDelta: DecisionCfg = {
  context: "2027년 스마트도시통합센터 정보시스템 통합유지보수 용역 · 경기도 안양시 · 사업기회 11866",
  basis: "완료된 변경 비교가 없어요. 입력 가능은 참여 권고가 아니에요.",
  checks: [
    { label: "최신 차수 확인", description: "R26BK01844973 · 차수 000", status: "success" }, { label: "결정 값 선택", description: "참여 또는 불참" },
    { label: "결정 이유 입력", description: "필수" }, { label: "담당자 이름", description: "사이드바 담당자 칸" },
  ],
  activeCheck: 1,
  freshness: { label: "현재성 미확인 · 결정 없음", tone: "neutral" },
  evidence: [
    { id: "latest", title: "최신 공고 조건", aside: "최신 차수 R26BK01844973 · 차수 000 · 게시 11.20 15:40", body: (
      <Facts columns={3} facts={[{ label: "입찰 마감", value: "12월 02일 10:00 · D-9", strong: true }, { label: "추정가격", value: "1,941,213,636원", strong: true }, { label: "최신 공고", value: "R26BK01844973 · 차수 000", strong: true }]} />
    ) },
    { id: "delta", title: "직전 차수 변경", body: <Para dim>비교할 직전 차수가 없어요.</Para> },
    { id: "terms", title: "참가 요건과 공고 조건", body: (
      <Facts columns={2} facts={[
        { label: "예산", value: "2,150,030,560원" }, { label: "추정가격", value: "1,941,213,636원" },
        { label: "입찰마감", value: "2026.12.02 10:00" }, { label: "개찰일", value: "2026.12.02 11:00" },
        { label: "계약방법", value: "일반경쟁" }, { label: "낙찰방법", value: "협상에의한계약(SW사업)" },
        { label: "참가제한", value: "N · 제한 없음" }, { label: "업종제한", value: "Y · 제한 있음" },
        { label: "공동수급", value: "(전자)공동이행" }, { label: "기술평가비율", value: "90" },
        { label: "지역제한 근거", value: "값 없음" }, { label: "재공고", value: "Y · 재공고" },
      ]} />
    ) },
  ],
  decision: { stateLabel: "현재 사람 결정", state: undecided, hint: "저장하면 되돌릴 수 없어요.", actions: [{ label: "결정 확인", kind: "primary", disabled: true }] },
};

/* ── 오늘 할 일 ────────────────────────────────────────────────────────── */

const dashboard: OverviewCfg = {
  kpis: [
    { label: "마감 임박 추적 건", value: "3건", note: "7일 이내" }, { label: "최종 Go/No-Go", value: "2건", note: "미결정·재검토·공고 확인 필요" },
    { label: "사업기회 조치 필요", value: "0건", note: "새 연결·후보·확인 항목·보류 기한" }, { label: "필수 검토 발주계획", value: "829건", note: "추적 결정 대기 · 모델 관련" },
    { label: "사전규격 검토할 항목", value: "88건", note: "개요 확인·추적 결정 · 마감 전" },
  ],
  collection: [
    { name: "발주계획", mark: { label: "정상", tone: "success" }, line: "최근 기준일 11-22 · 수집 11월 23일 · C-2 성공 · 필수 검토 1건 · 훑어보기 3건" },
    { name: "공고(사전규격·입찰공고)", mark: { label: "수집 완료", tone: "success" }, line: "최근 기준일 11-22 · 적재 11월 23일 · 적재 경고 162건" },
  ],
  queues: [
    { title: "마감 임박 추적 건", link: "사업기회", foot: "추적 중·보류 사업 중 7일 이내 · 11.23 19:19 기준", items: [
      { id: "q1", title: "2027 서초 빅데이터 플랫폼 유지보수 용역", meta: "의견등록 마감 · 계속 추적", deadline: { text: "내일 마감", level: "urgent" }, kind: "추적 건 마감" },
      { id: "q2", title: "2027년 용인시 행정정보 운영시스템 통합유지관리 용역", meta: "입찰 마감 · 계속 추적", deadline: { text: "D-2", level: "urgent" }, kind: "추적 건 마감" },
      { id: "q3", title: "2027년 지적정보시스템 통합 유지관리 용역", meta: "입찰 마감 · 계속 추적", deadline: { text: "D-3", level: "soon" }, kind: "추적 건 마감" },
    ] },
    { title: "최종 결정 대기", link: "최종 Go/No-Go", foot: "입찰 마감순 · 검토 대상 2건", items: [
      { id: "q4", title: "2027년 용인시 행정정보 운영시스템 통합유지관리 용역", meta: "경기도 용인시 · 추정가격 253,745,455원 · 미결정", deadline: { text: "D-2", level: "urgent" }, kind: "최종 Go/No-Go" },
      { id: "q5", title: "2027년 스마트도시통합센터 정보시스템 통합유지보수 용역", meta: "경기도 안양시 · 추정가격 1,941,213,636원 · 미결정", deadline: { text: "D-9", level: "normal" }, kind: "최종 Go/No-Go" },
    ] },
  ],
  checks: [
    { label: "보류 재검토", value: "0건", note: "기한 지남 · 14일" }, { label: "사전규격 확인 필요", value: "36건", note: "개요 실패·취소 · 문서 준비 중단" },
    { label: "개요 사람 확인", value: "16건", note: "사전규격 · 누적" }, { label: "확인 항목 미답변", value: "0건", note: "조치 필요 사업" },
    { label: "훑어보기 발주계획", value: "783건", note: "모델 불확실 · 추적 미선택" },
  ],
  stages: [
    { stage: "발주계획", waiting: "829건", due: "값 없음", tracked: "1건", next: "관련 829건에서 추적 여부 정하기" },
    { stage: "사전규격", waiting: "88건", due: "88건", tracked: "7건", next: "개요 확인 뒤 추적 시작 · 오늘 마감 8건" },
    { stage: "사업기회", waiting: "0건", due: "3건", tracked: "9건", next: "마감 임박 3건 확인" },
    { stage: "최종 Go/No-Go", waiting: "2건", due: "1건", tracked: "2건", next: "용인시 건 D-2 결정" },
  ],
};

/* ── 화면 표 ───────────────────────────────────────────────────────────── */

export interface PageDef {
  id: string; title: string; navPage: string; template: string; crumbs?: Crumb[];
  actions?: ReactNode; render: () => ReactNode;
}

const refresh = <Button label="새로고침" variant="ghost" size="sm" />;

export const PAGES: PageDef[] = [
  { id: "dashboard", title: "오늘 할 일", navPage: "dashboard", template: "P5 요약", actions: <>{refresh}<Button label="실행 상태" variant="secondary" size="sm" /></>, render: () => <OverviewView cfg={dashboard} /> },
  { id: "briefing", title: "오늘의 브리핑", navPage: "dashboard", template: "P1 작업 화면", render: () => <Workspace cfg={briefing} /> },
  { id: "order-plans", title: "발주계획", navPage: "order-plans", template: "P1 작업 화면", render: () => <Workspace cfg={orderPlans} /> },
  { id: "pre-specs", title: "사전규격", navPage: "pre-specs", template: "P1 작업 화면", render: () => <Workspace cfg={preSpecs} /> },
  { id: "pre-spec-detail", title: "사전규격 상세", navPage: "pre-specs", template: "P2 읽기 상세", crumbs: [{ label: "사전규격", page: "pre-specs" }, { label: "사전규격 #4141" }], render: () => <RecordView cfg={preSpecDetail} /> },
  { id: "opportunities", title: "사업기회", navPage: "opportunities", template: "P1 작업 화면", render: () => <Workspace cfg={opportunities} /> },
  { id: "opportunity-record", title: "사업기회 레코드", navPage: "opportunities", template: "P2 읽기 상세", crumbs: [{ label: "사업기회", page: "opportunities" }, { label: "사업기회 #11866" }], actions: <><Button label="판정 보기" variant="secondary" size="sm" isDisabled /><Button label="제안서 초안" variant="secondary" size="sm" isDisabled /></>, render: () => <RecordView cfg={opportunityRecord} /> },
  { id: "notice-detail", title: "입찰공고 상세", navPage: "opportunities", template: "P2 읽기 상세", crumbs: [{ label: "사업기회", page: "opportunities" }, { label: "입찰공고 상세" }, { label: "공고 4087" }], actions: <Button label="판정 기준" variant="secondary" size="sm" />, render: () => <RecordView cfg={noticeDetail} /> },
  { id: "bid-delta", title: "입찰 참여 결정", navPage: "opportunities", template: "P3 최종 결정", crumbs: [{ label: "사업기회", page: "opportunities" }, { label: "#11866", page: "opportunity-record" }, { label: "입찰 참여 결정" }], actions: <Button label="결정 목록으로" variant="ghost" size="sm" />, render: () => <DecisionView cfg={bidDelta} /> },
  { id: "go-no-go", title: "최종 Go/No-Go", navPage: "go-no-go", template: "P1 작업 화면", render: () => <Workspace cfg={goNoGo} /> },
  { id: "company", title: "회사 근거", navPage: "company", template: "P1 작업 화면(관리)", render: () => <Workspace cfg={company} /> },
  { id: "criteria", title: "판정 기준", navPage: "criteria", template: "P1 작업 화면(관리)", render: () => <Workspace cfg={criteria} /> },
  { id: "run-status", title: "실행 상태", navPage: "run-status", template: "P1 작업 화면(관리)", actions: <>{<Button label="운영 조건" variant="ghost" size="sm" />}{refresh}</>, render: () => <Workspace cfg={runStatus} /> },
];

/*
 * 분석·제안 페이지. 2026-11-23 운영 웹(bidops:list-review-sheets-20261123) 29개 주소를 GET 전용으로 열어 본 결과다.
 */
import { useState } from "react";
import { Table, pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { Heading, Text } from "@astryxdesign/core/Text";

interface PageRow extends Record<string, unknown> { page: string; purpose: string; show: string; found: string; proposal: string; template: string }
interface TemplateRow extends Record<string, unknown> { id: string; name: string; astryx: string; used: string; found: string }
interface VariantRow extends Record<string, unknown> { name: string; idea: string; changes: string; keeps: string; cost: string }

const PAGE_ROWS: PageRow[] = [
  { page: "오늘 할 일 (/)", template: "P5 요약",
    purpose: "출근 직후 오늘 사람이 정해야 할 일과 수집이 정상인지 확인하고 해당 업무 화면으로 이동합니다.",
    show: "① 오늘 마감이 걸린 결정(추적 건 마감·최종 결정 대기) ② 업무량(단계별 대기 건수) ③ 일일 수집 상태 ④ 확인할 것",
    found: "건수 칸 5개가 테두리 카드이고 숫자가 초록입니다(다른 화면의 숫자는 먹색). '확인할 것'은 채움 상자, 목록은 선 구분으로 구역마다 그리는 방식이 다릅니다. 가장 급한 결정 목록이 건수 칸과 수집 줄 아래에 있습니다.",
    proposal: "건수 칸·수집 줄·결정 목록을 공용 구역(T10)·사실 목록(T9)·마감 글자(T8)로 통일합니다. 결정 목록 행은 목록 화면과 같은 행 부품을 씁니다." },
  { page: "오늘의 브리핑 (/briefing)", template: "P1 작업 화면",
    purpose: "Slack 브리핑으로 받은 추천 건을 웹에서 이어서 보고 추적 여부를 정합니다.",
    show: "① 오늘 추천 건과 내 반응 ② 고른 건의 개요 미리보기 ③ 추적 시작",
    found: "운영에는 브리핑이 없어 빈 상태만 보입니다. 빈 상태의 주 버튼이 검정이고 다른 화면의 주 버튼은 초록입니다.",
    proposal: "브리핑이 생기면 사전규격 목록과 같은 작업 화면 틀을 씁니다. 빈 상태 버튼은 공용 빈 상태(T10)의 primary 하나로 맞춥니다." },
  { page: "발주계획 (/order-plans)", template: "P1 작업 화면",
    purpose: "하루 400~600건 가운데 모델이 관련으로 본 건을 훑어 추적할 사업을 일찍 고릅니다.",
    show: "① 사업명·기관·예산·발주 예정 ② 모델이 관련으로 본 이유와 근거 위치 ③ 추적 시작·보류·종료·넘기기",
    found: "목록 머리 글자 13px(사전규격은 16px), 상태 열이 비어 있음, 결정 띠가 밑줄 링크+버튼 4개로 사전규격과 순서·모양이 다릅니다. 담당자 이름이 없을 때 주 버튼이 옅은 초록이라 켜진 것처럼 보입니다.",
    proposal: "목록 머리·선택 도구·열 머리·행·쪽 이동·결정 띠를 사전규격과 같은 부품으로 그립니다. 결정 띠 순서는 [현재 상태] … [넘기기][추적 종료][보류][추적 시작]으로 고정합니다." },
  { page: "사전규격 목록 (/pre-specs)", template: "P1 작업 화면",
    purpose: "의견 마감 전에 개요를 확인하고 추적을 시작할 건을 고릅니다. 선택한 건을 차례로 상세 검토합니다.",
    show: "① 의견 마감(오늘·D-n) ② 개요 상태(완료·사람 검토 필요) ③ 예산·기관 ④ 추적 시작·검토 제외·상세 열기",
    found: "마감이 '오늘 23:59 마감' 초록 고정폭 글자 + 날짜 두 줄입니다(Go/No-Go는 빨강 'D-2 · 11.25', 대시보드는 '내일 마감'). 미리보기 사실이 2열 큰 숫자인데 Go/No-Go는 아이콘 칸 3개입니다. 주 버튼이 '상세 페이지 열기'(초록)이고 결정인 '추적 시작하기'는 옅게 보입니다.",
    proposal: "마감은 공용 마감 글자(T8) 한 형식으로, 사실은 사실 목록(T9)으로 통일합니다. 화면의 주 버튼은 결정 행동(추적 시작) 하나로 둡니다." },
  { page: "사전규격 상세 (/pre-specs/:id)", template: "P2 읽기 상세",
    purpose: "제안요청서 개요를 원문 쪽과 대조해 읽고 추적을 시작할지 정합니다.",
    show: "① 마감·예산·구분 ② 사업 개요와 주요 과업(주장마다 쪽 링크) ③ 원문·첨부 ④ 추적 시작",
    found: "읽기 폭 1040px·하단 결정 띠는 잘 잡혀 있습니다. 사실 칸(세로선 4칸)과 품질 표식(회색 상자)이 사업기회 레코드와 다른 모양입니다. '목록' 복귀 줄이 위치 줄과 겹칩니다.",
    proposal: "머리(상위 문구·제목·상태)와 사실 목록을 사업기회 레코드와 같은 부품으로 그립니다. 본문 구역은 공용 구역(T10)·주장 목록으로 둡니다." },
  { page: "사업기회 목록 (/opportunities)", template: "P1 작업 화면",
    purpose: "추적 중인 사업의 단계와 마감을 관리하고, 후보 연결·확인 항목 같은 예외를 처리합니다.",
    show: "① 조치가 필요한 건 ② 추적 중 사업의 현재 단계와 다음 마감 ③ 연결된 공고 ④ 추적 상태 변경",
    found: "기본 보기 '조치 필요'가 0건이면 목록이 비고 미리보기에는 다른 건이 남습니다. 미리보기 안 탭이 알약 모양(다른 화면은 밑줄 탭), 단계 표시가 직접 그린 번호 원입니다.",
    proposal: "단계는 사업 흐름 부품(T12, Stepper)으로 통일합니다. 미리보기 머리·사실·결정 띠를 다른 목록과 맞춥니다." },
  { page: "사업기회 레코드 (/opportunities/:id/*)", template: "P2 읽기 상세",
    purpose: "한 사업의 전체 흐름(발주계획→사전규격→입찰공고→결정)과 활동 기록을 한곳에서 봅니다.",
    show: "① 지금 단계와 마감 ② 사업 흐름 ③ 추적 상태와 사유 ④ 판정·제안서(꺼져 있으면 그 사실) ⑤ 활동 노트",
    found: "오른쪽 '추적 상태'가 테두리 카드입니다(패널 안 카드 금지 규칙과 어긋남). 사실이 머리의 한 줄 + 오른쪽 표 두 군데에 나뉘어 반복됩니다. 6개 탭 중 4개가 꺼짐·준비 중 안내만 보여 줍니다. 추적 결정이 하단 띠가 아니라 본문 링크입니다.",
    proposal: "추적 상태 변경을 사전규격 상세와 같은 하단 결정 띠로 옮깁니다. 사실은 한 곳(사실 목록)에만 둡니다. 꺼진 탭은 공용 안내 구역 한 형식으로 그립니다." },
  { page: "입찰공고 상세 (/judgments/:pk, /queue)", template: "P2 읽기 상세",
    purpose: "입찰공고 한 건의 공고 조건·자격 제약·판정 요약을 회차 기준으로 확인합니다.",
    show: "① 마감·금액 ② 판정 등급(없으면 '판정 없음') ③ 공고 정보·자격 제약 ④ 생애주기",
    found: "옛 양식이 그대로입니다. 본문에 큰 제목(사전규격 상세)이 다시 있고, 테두리 카드·청록 테두리 표식·고정폭 글자·자체 목록을 씁니다. 제목도 '입찰공고 상세'와 '사전규격 상세'가 섞여 있습니다.",
    proposal: "읽기 상세 틀로 옮깁니다. 가장 효과가 큰 정리 대상입니다. 회차 선택은 위치 줄 오른쪽에 그대로 둡니다." },
  { page: "입찰 참여 결정 (/opportunities/:id/bid-delta)", template: "P3 최종 결정",
    purpose: "최신 공고 조건과 차수 간 변경을 확인하고 사람이 Go/No-Go를 기록합니다. 저장하면 되돌릴 수 없습니다.",
    show: "① 최신 차수와 마감 ② 직전 차수 대비 변경 ③ 참가 요건 ④ 결정 값·이유·담당자 ⑤ 저장 전 확인 조건",
    found: "참가 요건 표가 격자선 표로, 다른 화면의 사실 표시와 다릅니다. 담당자 이름을 이 화면만 따로 입력받습니다(다른 화면은 사이드바 칸). '확인됨/필요' 조건 표시가 작은 색 글자입니다.",
    proposal: "요건 표는 사실 목록(T9)으로, 저장 전 조건은 사업 흐름 부품(T12)으로 그립니다. 담당자 이름은 사이드바 한 값으로 맞춥니다. 결정 값·이유·경계 문구는 그대로 둡니다." },
  { page: "최종 Go/No-Go (/go-no-go)", template: "P1 작업 화면",
    purpose: "입찰공고까지 온 추적 사업 중 결정이 필요한 건을 마감순으로 보고 결정 화면으로 들어갑니다.",
    show: "① 입찰 마감 ② 사람 결정 상태(미결정·Go·No-Go·재검토) ③ 최신 공고 조건 ④ 결정 화면 열기",
    found: "행이 3줄이고 글자가 다른 목록보다 큽니다(16px). 쪽 이동 줄에 '전체 2건'이 두 번 나옵니다. 사실이 아이콘 칸 3개로 다른 미리보기와 다릅니다.",
    proposal: "다른 세 목록과 같은 행·쪽 이동·미리보기 부품으로 그립니다." },
  { page: "회사 근거 (/company)", template: "P1 작업 화면(관리)",
    purpose: "판정에 쓰는 회사 자격·실적·인력·선호와 각 항목의 확인 상태를 봅니다(읽기 전용).",
    show: "① 확인이 필요한 항목 ② 항목별 값·출처·유효기간 ③ 미확인은 미확인으로",
    found: "운영에는 등록된 근거가 없어 빈 상태만 보입니다.",
    proposal: "등록되면 관리 화면 틀(목록|상세)로 그립니다. 시안의 값은 예시이며 미확인을 추정으로 채우지 않습니다." },
  { page: "판정 기준 (/criteria 외 5개 주소)", template: "P1 작업 화면(관리)",
    purpose: "발주계획 선별(C-2) 정책의 활성 버전·게이트 결과·일일 자동 실행을 확인하고, 공고 판정(C-1) 기준을 관리합니다.",
    show: "① 지금 운영 활성 버전 ② 게이트 통과 여부와 지표 ③ 일일 자동 실행 스위치 ④ 활성화·교체",
    found: "목록|상세가 안쪽 여백을 둔 상자 배치라 발주계획 등(패널 끝까지 채움)과 격자가 다릅니다. 탭이 2단(밑줄 탭 + 알약 탭)입니다. 상태 표식 글자가 16px로 다른 화면(13px)보다 큽니다. 하단 '운영 활성'이 버튼처럼 보이는 표식입니다.",
    proposal: "작업 화면 틀을 같이 써서 목록 머리·행·미리보기·하단 띠를 맞춥니다. 2단 탭은 보기 탭 + 목록 머리의 하위 보기로 정리합니다." },
  { page: "실행 상태 (/run-status 외 4개 주소)", template: "P1 작업 화면(관리)",
    purpose: "일일 수집·판정 회차가 정상으로 끝났는지 확인하고, 실패·미판정이 있으면 원인을 보고 수동 실행합니다.",
    show: "① 문제 있는 회차 ② 회차별 단계 진행 ③ 실패 사유와 재시작 가능 여부 ④ 수동 실행",
    found: "판정 기준과 같은 문제(안쪽 여백 배치·큰 표식)에 더해, 57개 회차가 전부 같은 '판정 실행 없음' 표식이라 문제 회차가 눈에 띄지 않습니다. 단계 진행이 직접 그린 원입니다.",
    proposal: "작업 화면 틀 + 사업 흐름 부품(단계 진행)으로 그립니다. 확인이 필요한 회차가 위로 오게 합니다(시안 2는 상태 묶음)." },
];

const TEMPLATE_ROWS: TemplateRow[] = [
  { id: "P0", name: "셸(사이드바·흰 패널·위치 줄)", astryx: "Breadcrumbs, Heading (배치는 프로젝트 소유 · ADR-0040·0076)", used: "모든 화면", found: "상세 화면마다 복귀 줄·탭 줄이 따로 있음" },
  { id: "P1", name: "작업 화면(보기 줄 + 목록 | 미리보기 + 결정 띠)", astryx: "TabList, Toolbar, Table, List, Pagination · 템플릿 table-filter·table-grouped·incident-console", used: "발주계획·사전규격·사업기회·최종 Go/No-Go·브리핑·관리 3화면", found: "8화면이 같은 구조인데 CSS 파일 6개가 각각 그림" },
  { id: "P2", name: "읽기 상세(머리 + 사실 + 구역 + 결정 띠)", astryx: "MetadataList, Stepper, Outline · 템플릿 detail-page", used: "사전규격 상세·사업기회 레코드·입찰공고 상세", found: "세 화면의 머리·사실·결정 위치가 모두 다름" },
  { id: "P3", name: "최종 결정(근거 | 결정 입력)", astryx: "RadioList, TextArea, Stepper · 템플릿 payment-form", used: "입찰 참여 결정", found: "격자선 표·자체 담당자 입력" },
  { id: "P5", name: "요약(건수 + 수집 + 결정 목록)", astryx: "List, MetadataList · 템플릿 dashboard-project-status", used: "오늘 할 일", found: "구역마다 카드·채움·선이 섞임" },
  { id: "T1", name: "보기 줄", astryx: "TabList + Tab(건수 endContent), TextInput, Token", used: "P1 전부", found: "관리 화면만 2단 탭" },
  { id: "T2·T3", name: "목록 머리 · 선택 도구", astryx: "Toolbar(Bulk Actions), SegmentedControl", used: "P1 전부", found: "글자 13/16px 혼재, 밀도 선택이 사전규격에만 있음" },
  { id: "T4", name: "목록 행", astryx: "프로젝트 격자 행(↑↓ 행 이동 때문에 행 요소를 소유) / 시안 1은 Table, 시안 3은 List", used: "P1 전부", found: "2줄·3줄, 14/16px, 상태 열 유무가 화면마다 다름" },
  { id: "T5", name: "쪽 이동", astryx: "Pagination", used: "P1 전부", found: "버튼·건수 문구·크기가 세 가지" },
  { id: "T6", name: "미리보기", astryx: "Heading, MetadataList, TabList", used: "P1 전부", found: "위치(1/829) 표시·안쪽 탭·사실 모양이 제각각" },
  { id: "T7", name: "결정 띠", astryx: "Button(primary 1개), Kbd", used: "P1·P2·P3", found: "네 목록이 네 가지 배치. 주 버튼이 결정이 아닌 이동인 화면이 있음" },
  { id: "T8", name: "상태 표식 · 분류 표식 · 마감 글자", astryx: "Token(채움), Token, Timestamp", used: "모든 화면", found: "주황·보라·회색 채움 표식, 16px 표식, 청록 테두리 표식, 마감 표기 4종" },
  { id: "T9", name: "사실 목록", astryx: "MetadataList", used: "모든 화면", found: "2열 큰 숫자, 세로선 4칸, 아이콘 칸 3개, 격자선 표, 한 줄 나열 5종" },
  { id: "T10", name: "구역 · 채움 블록 · 빈 상태 · 주장 목록", astryx: "Heading, EmptyState, Banner", used: "모든 화면", found: "빈 상태 주 버튼이 검정" },
  { id: "T12", name: "사업 흐름·단계 진행", astryx: "Stepper, Step", used: "사업기회·레코드·입찰공고 상세·실행 상태·결정", found: "번호 원, 세로 원, 점선 원 등 직접 그린 것 4종" },
  { id: "T13", name: "요약 줄", astryx: "MetadataList(가로)", used: "관리 3화면", found: "판정 기준 C-1과 실행 상태가 같은 모양, C-2에는 없음" },
];

const VARIANT_ROWS: VariantRow[] = [
  { name: "유지안 · 컴포넌트만 교체", idea: "2026-11-21 승인 배치와 격자를 그대로 둡니다. 직접 그린 부품만 Astryx 컴포넌트와 공용 부품으로 바꿉니다.",
    changes: "상태 표식(채움 한 벌), 사실 목록, 쪽 이동, 선택 도구, 단계 진행, 결정 띠 순서, 빈 상태 버튼", keeps: "목록 56% | 미리보기 44%, 읽기 폭 1040px, 관리 화면의 안쪽 여백 배치, 사업기회 레코드의 오른쪽 열", cost: "가장 작음. 화면 검사 기준 이미지만 갱신. 관리 화면과 목록 화면의 격자 차이는 남습니다." },
  { name: "시안 1 · 표 작업대", idea: "Astryx table-filter·detail-page·settings-sidebar 구조를 따릅니다. 많은 건을 열 단위로 훑고 정렬·필터로 좁히는 데 맞춥니다.",
    changes: "목록이 열이 있는 표(기관·예산·상태·마감), 적용 필터 토큰, 미리보기는 라벨-값 세로 목록, 레코드는 본문+오른쪽 정보 열, 관리 화면은 왼쪽 구역 메뉴", keeps: "보기 탭, 선택·일괄 처리, 하단 결정 띠, 사람 결정 경계", cost: "중간. 발주계획·사전규격 행의 ↑↓ 이동을 표 첫 열 버튼 방식으로 옮겨야 합니다(사업기회·Go/No-Go가 이미 쓰는 방식). 긴 한글 제목이 한 줄로 잘립니다." },
  { name: "시안 2 · 묶음 검토", idea: "Astryx table-grouped·incident-console 구조를 따릅니다. 마감·상태로 묶어 '지금 볼 것'이 위로 오게 합니다.",
    changes: "목록이 마감·상태 묶음(접기 가능), 미리보기 위에 사업 흐름, 관리 화면은 요약 칸 + 상태 묶음, 결정 화면은 한 열 + 저장 전 단계, 오늘 할 일은 결정 목록 + 오른쪽 정보 열", keeps: "행 모양(2줄), 56|44 분할, 선택·일괄 처리, 하단 결정 띠", cost: "중간. 묶음은 서버가 페이지 분할 전에 정해야 하므로 목록 API에 묶음 기준이 필요합니다(브라우저에서 받은 페이지만 묶지 않음)." },
  { name: "시안 3 · 읽기 집중", idea: "목록을 좁은 길잡이로 줄이고 미리보기를 넓혀 상세 화면으로 넘어가는 횟수를 줄입니다. 읽기 화면에는 구역 목차를 둡니다.",
    changes: "목록 36% | 미리보기 64%, 미리보기 안 탭(요약·근거·이력), 사실 4열, 읽기 상세·결정 화면 왼쪽에 구역 목차(Outline)", keeps: "보기 탭, 하단 결정 띠, 읽기 폭", cost: "큼. 목록에 한 번에 보이는 정보가 줄고 선택·일괄 처리 도구가 좁은 칸에 들어갑니다. 미리보기 탭별 데이터 조회가 늘어납니다." },
];

const pageColumns: TableColumn<PageRow>[] = [
  { key: "page", header: "화면", width: pixel(150) },
  { key: "purpose", header: "만든 목적", width: proportional(1.2) },
  { key: "show", header: "사용자에게 보여 줄 것(순서대로)", width: proportional(1.2) },
  { key: "found", header: "운영 화면에서 본 것", width: proportional(1.5) },
  { key: "proposal", header: "제안", width: proportional(1.3) },
  { key: "template", header: "화면 틀", width: pixel(110) },
];
const templateColumns: TableColumn<TemplateRow>[] = [
  { key: "id", header: "번호", width: pixel(70) },
  { key: "name", header: "공용 템플릿", width: proportional(1.2) },
  { key: "astryx", header: "쓰는 Astryx 컴포넌트·템플릿", width: proportional(1.6) },
  { key: "used", header: "쓰는 화면", width: proportional(1.1) },
  { key: "found", header: "지금 갈라져 있는 모습", width: proportional(1.5) },
];
const variantColumns: TableColumn<VariantRow>[] = [
  { key: "name", header: "안", width: pixel(170) },
  { key: "idea", header: "생각", width: proportional(1.3) },
  { key: "changes", header: "바뀌는 것", width: proportional(1.3) },
  { key: "keeps", header: "그대로 두는 것", width: proportional(1) },
  { key: "cost", header: "구현 부담·주의", width: proportional(1.3) },
];

interface FindingRow extends Record<string, unknown> { item: string; found: string; answer: string }
interface ModeRow extends Record<string, unknown> { name: string; idea: string; changes: string; rows: string; cost: string }

/* 2026-11-23 시안 1(표 작업대)로 정한 뒤, 시안 1 화면에서 잰 값이다(1440×900, 13개 화면). */
const FINDING_ROWS: FindingRow[] = [
  { item: "밝은 글자(#E8E4E2)", found: "시안의 루트가 OS 다크 모드를 따라가 본문 글자색이 다크 테마 값으로 풀렸고, 그 색을 물려받는 목록 머리·요약 값·브랜드 이름·선택 건수가 밝은 바탕 위 밝은 글자로 나왔습니다. 운영 웹은 본문 색이 고정이라 같은 문제가 없습니다(6개 화면 확인).",
    answer: "네 방안 공통으로 고쳤습니다. 루트를 라이트로 고정하고 해당 글자가 본문 먹색(#1B1B1A)을 직접 읽습니다. 다크 모드에서 밝은 바탕 위 밝은 글자 0건." },
  { item: "글자 대비", found: "글자 요소 1,137개 모두 바탕 대비 4.5:1 이상입니다(투명도로 흐려지는 비활성 단추는 이 측정에 잡히지 않습니다).", answer: "색은 더 바꾸지 않았습니다. 남은 과제는 색이 아니라 크기·잘림·찾기입니다." },
  { item: "작은 글자", found: "글자의 26%가 12px입니다(상태 표식, 보조 문구, 라벨, 단축키 안내).", answer: "1-A와 1-C의 '글자 크게'는 한 단씩 올려 최소 13px, 본문 15px로 둡니다." },
  { item: "사업명 잘림", found: "표는 사업명을 한 줄로 자릅니다. 사업명 열은 1440px에서 249px(한글 약 17자), 1280px에서 153px(약 10자)입니다. 이 업무에서 사업명은 건을 가려내는 첫 단서입니다.", answer: "1-A와 1-C의 보통·넓게 밀도는 사업명을 두 줄까지 보여 주고 발주기관을 그 아래 줄에 둡니다." },
  { item: "우선순위 열의 위치", found: "마감·상태가 표의 맨 오른쪽 끝에 있어 사업명에서 시선이 가장 멀리 이동합니다. 행 사이 구분은 옅은 선뿐입니다.", answer: "1-B는 마감·상태를 사업명 바로 옆으로 옮기고, 줄무늬·고정 열 머리·급한 행의 왼쪽 띠를 넣습니다." },
  { item: "핵심 값 찾기", found: "미리보기의 마감·금액이 다른 사실과 같은 크기의 라벨-값 목록에 섞여 있습니다.", answer: "1-B는 마감·금액을 위쪽 큰 글자 띠로 올리고 나머지를 목록으로 둡니다." },
  { item: "모니터·사람 차이", found: "지원 폭이 1280~1920px이고 같은 화면을 훑는 날과 꼼꼼히 읽는 날이 다릅니다. 운영 사전규격에는 이미 밀도 선택(촘촘)이 있습니다.", answer: "1-C는 글자 크기·행 밀도·표시할 열·미리보기 접기와 너비를 사용자가 고릅니다." },
];

const MODE_ROWS: ModeRow[] = [
  { name: "시안 1 기준", idea: "정해진 배치 그대로입니다. 비교의 기준입니다.", changes: "없음(밝은 글자 수정만 포함)", rows: "16 / 19 / 25행", cost: "—" },
  { name: "1-A 크게 보기", idea: "모두에게 같은, 더 크고 덜 잘리는 화면을 줍니다.", changes: "글자 한 단 올림(최소 13px), 행 높이 넓힘, 사업명 두 줄 + 발주기관 아래 줄, 식별 줄을 먹색으로", rows: "6 / 8 / 12행",
    cost: "한 화면에 보이는 행이 절반 아래로 줄어듭니다. 하루 수백 건을 훑는 발주계획에는 부담이 큽니다." },
  { name: "1-B 훑기 길잡이", idea: "크기와 밀도는 그대로 두고, 눈이 길을 잃지 않게 길잡이를 넣습니다.", changes: "줄무늬 행, 고정 열 머리, 마감·상태 열을 사업명 옆으로, 급한 행 왼쪽 띠, 남은 날(D-2) 굵게, 미리보기·레코드의 핵심 수치 띠", rows: "16 / 19 / 25행",
    cost: "행 수는 그대로입니다. 급한 건이 몰린 날은 띠가 연달아 이어집니다. 사업명 잘림과 12px 글자는 그대로 남습니다." },
  { name: "1-C 내 화면 맞춤", idea: "한 가지 정답을 정하지 않고 사용자가 자기 모니터와 일에 맞춥니다.", changes: "위치 줄의 보기 설정: 글자 크기, 행 밀도(촘촘·보통·넓게), 표시할 열, 미리보기 접기, 미리보기 너비 끌어 조절", rows: "촘촘 16 / 19 / 25행 (밀도에 따라 줄어듦)",
    cost: "설정을 기억하는 기능이 새로 필요합니다(저장 위치와 범위를 정해야 함). 사람마다 화면이 달라 캡처 공유 때 같은 모습이 아닐 수 있습니다." },
];

const findingColumns: TableColumn<FindingRow>[] = [
  { key: "item", header: "살펴본 것", width: pixel(150) },
  { key: "found", header: "시안 1에서 확인한 것", width: proportional(1.4) },
  { key: "answer", header: "대응", width: proportional(1.2) },
];
const modeColumns: TableColumn<ModeRow>[] = [
  { key: "name", header: "방안", width: pixel(150) },
  { key: "idea", header: "생각", width: proportional(1) },
  { key: "changes", header: "바뀌는 것", width: proportional(1.4) },
  { key: "rows", header: "한 화면 행 수 · 사전규격 (1280 / 1440 / 1920px)", width: pixel(300) },
  { key: "cost", header: "대가·주의", width: proportional(1.3) },
];

export function AnalysisPage() {
  const [tab, setTab] = useState("modes");
  return (
    <div className="mk-doc">
      <div className="mk-doc-head">
        <Heading level={1}>Astryx 적용 분석과 제안</Heading>
        <Text type="body" color="secondary" display="block">
          2026-11-23 운영 웹 29개 주소를 읽기 전용으로 열어 화면의 목적, 보여 줄 것, 같은 기능이 다르게 그려지는 곳을 정리했습니다.
          네 안 모두 색·글꼴·셸(바탕 위 흰 패널)은 그대로이고, 추적 선택·최종 Go/No-Go를 사람이 정한다는 경계와 값 없음·미확인·0의 구분도 그대로입니다.
        </Text>
      </div>
      <TabList value={tab} onChange={setTab} hasDivider>
        <Tab value="modes" label="시안 1 보기 방안" />
        <Tab value="pages" label="화면별 분석" />
        <Tab value="templates" label="공용 템플릿" />
        <Tab value="variants" label="앞선 네 안 비교" />
      </TabList>
      <div className="mk-doc-table">
        {tab === "modes" ? (
          <div className="mk-doc-stack">
            <Text type="body" display="block">
              전체 배치는 시안 1(표 작업대)로 정했습니다. 아래는 그 위에서 실무자가 보기 편하게 만드는 세 방안입니다. 세 방안은 함께 쓸 수 있습니다.
              추천은 1-B의 길잡이를 기본 화면으로 하고, 1-C의 글자 크기·행 밀도 설정을 얹는 조합입니다. 1-A를 단독 기본값으로 쓰면 보이는 행이 절반 아래로 줄어듭니다.
            </Text>
            <Heading level={3}>시안 1에서 확인한 것</Heading>
            <Table data={FINDING_ROWS} columns={findingColumns} idKey="item" density="balanced" verticalAlign="top" />
            <Heading level={3}>세 방안</Heading>
            <Table data={MODE_ROWS} columns={modeColumns} idKey="name" density="balanced" verticalAlign="top" />
          </div>
        ) : null}
        {tab === "pages" ? <Table data={PAGE_ROWS} columns={pageColumns} idKey="page" density="balanced" verticalAlign="top" /> : null}
        {tab === "templates" ? <Table data={TEMPLATE_ROWS} columns={templateColumns} idKey="id" density="balanced" verticalAlign="top" /> : null}
        {tab === "variants" ? <Table data={VARIANT_ROWS} columns={variantColumns} idKey="name" density="balanced" verticalAlign="top" /> : null}
      </div>
    </div>
  );
}

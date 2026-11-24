/**
 * 사전규격 상세 `분석 완료` 화면(mock 빌드 전용)을 볼 수 있는 엔진 run 예시.
 *
 * 필드 이름과 구조는 원본 엔진 스키마(`packages/bid-deep-engine/src/bid_deep_engine/analysis/schemas.py`
 * `Analysis`·`GateResult`·`RequirementFit`·`Risk`·`ReviewActions`·`Assessment.provisional`·`RfpFacts.staffing`·
 * `ContractTerms`·`Evidence`)와 `engine_tests/report_factory.py`의 `make_analysis()`, BidOps가 덧붙이는
 * `analysis.source_evidence`(`adapter.source_evidence`)에서 옮겼다. 내용은 2026-11-21 시안
 * (`docs/1121_prespec-detail/mockups/index.html`)의 예시 데이터(`FITS`·`gates`·`risks`·`todos*`)다.
 *
 * **예시다.** 회사 근거 문구·판단은 실제 회사 역량이 아니며 운영 데이터도 품질 근거도 아니다
 * (`quality_status=mock_reference`). 원본 Analysis에는 요구사항 이름이 없으므로(`RequirementFit`은
 * `req_id`만 갖는다) 여기에도 넣지 않는다. 엔진 14756a0부터는 `fits[].name`으로 명칭이 오므로 완료 예시에만 싣는다.
 */
import type { OverviewRunPageText, OverviewRunResult } from "../../src/lib/types";
import type { WikiProject } from "../../src/lib/companyWikiApi";
import type { EngineAnalysis, EngineEvidence, EngineRun } from "../../src/lib/engineApi";

const SOURCE_SHA = "d".repeat(64);
const SOURCE_FILE = "제안요청서.hwpx";
export const DOCUMENT_VERSION_ID = "8c0f5d2e-4a51-4b8b-9a3e-2f3c1d6b7a10";

/** 인용 하나. 쪽이 있으면 원본 규칙대로 위치 하나(`exact`), 없으면 `unavailable`이다(Evidence validator). */
function evidence(quote: string, page: number | null, section = "S012"): EngineEvidence {
  return {
    quote,
    section_id: section,
    page,
    verified: true,
    repaired: false,
    locations: page === null ? [] : [{ file: SOURCE_FILE, file_sha256: SOURCE_SHA, page, start: 0, end: quote.length }],
    location_status: page === null ? "unavailable" : "exact",
  };
}

type FitCode = "FULL" | "PARTIAL" | "GAP" | "UNKNOWN";
/** 시안 `FITS`: [요구 ID, (시안의 표시 이름 — 응답에 없어 쓰지 않음), 대응, 회사 근거 수, 조치, 원문 발췌]. */
const FITS: [string, string, FitCode, number, string, string][] = [
  ["MPR-001", "홈페이지 프로그램 기능 개선 및 보완", "FULL", 2, "", "◦ 부서별 홈페이지 요청사항과 홈페이지 운영상 필요한 사항을 반영하여 프로그램 기능 개선 및 보완을 수행하여야 함."],
  ["MPR-002", "홈페이지 유지관리", "FULL", 2, "", "SSL 인증서 발급·갱신 및 교체 적용 3회"],
  ["MPR-003", "장애처리 및 지연", "PARTIAL", 1, "성남 인근 현장 대응 인력 또는 협력사를 확보해 2시간 내 현장 도착 체계를 마련한다.", "최초 장애 통보 후 2시간 이내 전문요원 현장 도착"],
  ["MPR-004", "전면 개편 홈페이지 안정화 및 하자보수 연계 지원", "PARTIAL", 1, "개편사업자 하자조치 요청·확인 절차를 수행계획서에 구체화한다.", "원인분석에 필요한 자료를 확인하여 개편사업자에게 하자조치를 요청"],
  ["MPR-005", "홈페이지 사용자 만족도 조사 및 참여 활성화", "UNKNOWN", 0, "", "홈페이지 사용자 만족도 조사는 최소 1회 이상 실시하여야 하며"],
  ["MPR-006", "콘텐츠 현행화 및 시민 생활밀착형 콘텐츠 발굴·구축 지원", "UNKNOWN", 0, "", "시민 이용빈도가 높거나 생활과 밀접한 정책·사업을 대상으로 콘텐츠 구축 후보 제시"],
  ["MHR-001", "사업수행 참여인력", "PARTIAL", 0, "성남 상주 가능한 웹개발·시스템관리 인력을 확보하거나 상주 방식을 협의한다.", "참여인력 중 상주 기술인력은 웹개발&시스템관리자로 1명 이상을 제시하여야 하며, 이 과업 수행을 위한 기술을 보유하여야 함"],
  ["MHR-002", "사업수행 참여인력의 복무기준", "GAP", 0, "성남 현지 상주 협력사 인력 확보 또는 원격 근무 조건을 발주처와 협의한다.", "참여인력은 성남시에서 제공하는 장소에서 상주하는 것을 원칙으로 하되"],
  ["SER-001", "개발 시 보안 준수사항 제시", "FULL", 2, "", "중요정보 및 개인정보가 전송되는 구간에 암호화 통신 적용"],
  ["SER-002", "정보시스템 이용 시 보안 준수사항", "FULL", 1, "", "정보시스템 기본 계정 및 불필요한 계정 삭제"],
  ["SER-003", "소프트웨어 개발보안(시큐어코딩) 관련 가이드 준수", "FULL", 1, "", "투입되는 인력에 대해 개발투입 전 소프트웨어 개발보안 관련 교육을 실시하고 교육 증빙을 제출하여야 함"],
  ["SER-004", "보안취약점 점검", "FULL", 2, "", "보안 취약점 점검(소스코드 보안약점 진단, 모의해킹 등)을 1회 이상 자체적으로 실시해야 함"],
  ["SER-005", "개인정보 보호", "FULL", 1, "", "개인정보보호를 위한 「개인정보보호법」등 관련 법규 준수"],
  ["COR-001", "하도급 인력관리 강화", "UNKNOWN", 0, "", "하도급 사전승인 절차를 이행해야 함"],
  ["COR-002", "작업장소 상호협의 결정 및 원격지 개발 활성화", "PARTIAL", 0, "대구 등 자사 작업장소를 제시하고 원격작업 보안대책을 관리·물리·기술적으로 수립한다.", "정보화 사업 수행을 위하여 필요한 작업장소는 성남시에서 제공하며, 설비 및 기타 작업환경은 계약상대자가 구비하여야 함"],
  ["COR-003", "지식재산권 및 SW산출물 활용 촉진", "FULL", 1, "", "사업수행 과정에서 취득 또는 작성하는 성과품 및 산출물 일체에 대한 지식재산권은 발주기관과 제안사(계약상대자)가 공동으로 소유함을 원칙으로 하되"],
  ["COR-004", "정보화 관련 법규 및 표준 지침 준수", "FULL", 2, "", "본 사업 추진과 관련하여 다음의 관련 법규 및 표준 지침을 준수하여야 함"],
  ["PER-001", "웹사이트 최적화", "FULL", 1, "", "웹페이지 용량은 3M 이하로 최소화하고 응답속도는 3초 이하여야 함"],
  ["QUR-001", "품질관리 및 표준절차 준수", "FULL", 1, "", "시스템에 대한 변경사항 발생 시 응용S/W 버전 관리 및 산출물 관리 등 유지보수 표준절차를 준수하여야 함"],
  ["SIR-001", "웹표준, 웹접근성, 웹호환성 준수", "FULL", 2, "", "웹접근성 품질마크 인증기준 준수 및 품질마크 갱신(비용은 사업자 부담)"],
  ["SIR-002", "표준 프레임 워크 적용", "FULL", 2, "", "기능 추가・개선 시 전자정부 표준프레임워크 기반(기획, 설계, 테스트, 운영 전 분야)으로 개발하여야 함"],
  ["SIR-003", "기술적용계획표 및 결과표 작성", "PARTIAL", 1, "제안자 관점 기술적용계획표와 준공 결과표 작성 담당과 절차를 확정한다.", "사업 준공 시 기술적용결과표를 제출하여야 함"],
  ["SIR-004", "내·외부 시스템과의 연계 관리", "FULL", 2, "", "타 시스템과 연계된 기능을 파악하여 원활하게 서비스 되도록 유지"],
  ["PMR-001", "보안관리 일반", "FULL", 1, "", "제안사는 사업 전체 단계별 보안관리 방안을 수립해야 함"],
  ["PMR-002", "누출금지 대상정보 및 보안 위규 처리", "FULL", 1, "", "제안사는 사업자 보안위규 처리기준을 숙지하며"],
  ["PMR-003", "참여인원 보안관리", "FULL", 2, "", "계약업체는 사업 투입 시 대표자 및 참여인원 대상으로 보안서약서를 제출해야 함"],
  ["PMR-004", "문서 및 자료 보안관리", "FULL", 1, "", "제안사는 발주기관으로부터 제공받은 제반 자료는 본 사업 이외의 목적에 사용할 수 없음"],
  ["PMR-005", "사무실 보안관리", "FULL", 1, "", "CCTV, 시건장치 등 비인가자 출입통제 대책이 마련된 공간을 확보하여 업무를 수행해야 하며"],
  ["PMR-006", "장비 및 매체 보안관리", "FULL", 1, "", "제안사는 PC, 노트북, 및 USB 등 관련 장비를 사업공간에 반출입할 수 없으며"],
  ["PMR-007", "네트워크 보안관리", "FULL", 1, "", "업무 수행 시 참여인력이 사용하는 PC(또는 노트북) 대상으로 인터넷 연결을 원칙적으로 금지하며"],
  ["PMR-008", "사업수행 협력체계 구축", "PARTIAL", 1, "LENA·Jennifer 등 제조사·공급사 및 MariaDB 기술지원업체와 확약 체계를 확보한다.", "주요 상용SW는 제조사 또는 공급사와 기술지원체계를 구축하고 기술지원확약서를 계약 후 10일 이내 제출"],
  ["PMR-009", "보고계획 및 제출서류", "FULL", 2, "", "예상 일정보다 과업 지연 시 계약상대자는 대처방안 등을 포함한 보고서를 성남시에 제출해야 함"],
  ["PMR-010", "비상연락망", "FULL", 1, "", "야간 및 공휴일 장애에 대비하여 24시간 무중단 비상대응체계가 수립되어야 함"],
  ["PMR-011", "산출물 현행화 및 제출", "FULL", 2, "", "유지관리 시 프로그램 변경에 따른 DB구조 및 기능 변경사항을 기존 산출물 및 관련 자료 등을 반영하여 현행화 실시"],
  ["PMR-012", "요구사항관리", "UNKNOWN", 0, "", "사업자는 요구사항을 빠짐없이 관리하고, 각각의 요구사항이 시스템에 반영 여부를 확인할 수 있도록 처리 결과를 제출하여야 함"],
  ["PMR-013", "인수인계", "FULL", 2, "", "계약상대자는 기존 사업자와의 원활한 업무 인수인계를 위하여 계약체결 후 즉시 관련 인원을 투입하여 완료 산출물을 확인하고 업무 인수를 받아야 함"],
  ["PMR-014", "안전관리", "PARTIAL", 0, "산업재해율 확인서 발급 여부를 확인하고 안전보건관리 계획서·위험성평가를 준비한다.", "산업재해율 확인서의 제출이 불가한 경우 그 사유를 제출"],
  ["PMR-015", "SW사업정보 저장소 데이터 작성 및 제출", "PARTIAL", 1, "기능점수 측정 전문가를 지정하거나 외부 측정 방안을 제안서에 명시한다.", "해당 사업 수주자는 SW사업정보 (SW사업 수행 및 실적 정보) 데이터를 작성하여 제출하여야 함"],
  ["PSR-001", "기술지원", "FULL", 2, "", "내·외부 시스템 연계를 위한 기술지원"],
  ["PSR-002", "교육지원", "FULL", 1, "", "사업 기간 중 정보기술에 대한 신기술 및 자료제공, 기술 자문 지원을 하여야 함"],
  ["PSR-003", "하자보수", "PARTIAL", 1, "성남 인근 대응 인력·협력사를 확보해 2시간 현장 도착과 365일 대응 체계를 갖춘다.", "장애접수 후 2시간 이내에 현장 도착, 4시간 이내 장애 조치를 하여야 하며, 365일 유지보수 요원의 신속한 대응이 이루어져야 함"],
];

const RATIONALE: Record<FitCode, string> = {
  FULL: "연결된 회사 실적의 수행 범위가 이 요구를 포함해요. (예시)",
  PARTIAL: "일부만 근거가 있어요. 조치가 필요해요. (예시)",
  UNKNOWN: "이 요구에 대응하는 회사 기록을 찾지 못했어요. (예시)",
  GAP: "회사 수행 기준과 맞지 않아요. (예시)",
};

/** 부분 결과에서 읽지 못한 범위(시안 b2의 Ⅳ장). 원본 Fit 값에 `읽기 실패`가 없으므로 UNKNOWN·근거 없음으로 둔다. */
const PARTIAL_UNREAD = /^(SER-00[1-5]|PMR-00[1-7])$/;

const RISKS: ["H" | "M" | "L", string, string, string, string][] = [
  ["H", "지역", "성남시 제공 장소 상주가 원칙이고 응용SW 개발자 1인 이상 상주가 요구된다. 회사의 상주 가능 지역 밖이어서 현 프로필로는 해소되지 않는다. (회사 기준은 예시)", "성남 현지 상주 가능한 협력사 인력을 확보하거나 상주 방식·장소를 발주처와 협의한다.", "참여인력은 성남시에서 제공하는 장소에서 상주하는 것을 원칙으로 하되"],
  ["M", "인력", "상주 기술인력은 사업시작 시점에 100% 투입해야 하고, 변경 시 사전 승인이 필요하다. 평가에 반영된 상주인력을 승인 없이 교체하면 계약 해지 사유가 된다.", "2027-01-01 착수 시점에 투입 가능한 인력과 대체인력 계획을 사전에 확정한다.", "상주 기술인력은 사업시작 시점에 100% 투입"],
  ["M", "계약", "장애 통보 후 2시간 내 현장 도착, 4시간 내 복구가 요구되며 미이행 시 배상책임과 지연배상금 공제가 따른다.", "성남 인근 현장 대응 협력사 또는 인력 확보 방안을 마련한다.", "최초 장애 통보 후 2시간 이내 전문요원 현장 도착"],
  ["M", "계약", "장애처리 지연 시 지연배상금이 월 유지관리비에서 공제된다. 월 3회 이상 복구 지연은 해지 사유가 될 수 있다.", "SLA 이행 체계(비상연락망, 24시간 대응)를 수행계획서에 구체화한다.", "지연배상금은 월 유지관리비에서 공제"],
  ["M", "기술", "유지관리 대상에 상용SW 10종이 포함되고, 제조사·공급사와의 기술지원확약서를 계약 후 10일 내 제출해야 한다.", "주요 상용SW 제조사·공급사와 확약 체계를 사전에 협의한다.", "주요 상용SW는 제조사 또는 공급사와 기술지원체계를 구축하고 기술지원확약서를 계약 후 10일 이내 제출"],
  ["M", "기술", "개편 홈페이지 하자보수 기간(2026.5~2027.4) 중 개편사업자와의 하자 연계·조치 확인과 종료 전 종합점검이 요구된다.", "하자 접수·요청·확인 절차와 이력 관리 방안을 수행계획서에 구체화한다.", "원인분석에 필요한 자료를 확인하여 개편사업자에게 하자조치를 요청"],
  ["M", "계약", "하도급은 사업금액의 50%를 초과할 수 없고 사전승인이 필요하며 재하도급은 원칙적 불허다. 공동수급은 공동이행방식만 가능하고 최소 지분율은 5%다.", "협력사 활용 시 공동이행 구성 또는 하도급 사전승인 계획을 확정한다.", "하도급 사전승인 절차를 이행해야 함"],
  ["M", "재무", "만족도 조사 참여 보상 비용 전액과 웹접근성 품질마크 갱신 비용을 계약상대자가 부담한다.", "보상 지급 규모를 발주처와 협의해 가격 산정에 반영한다.", "웹접근성 품질마크 인증기준 준수 및 품질마크 갱신(비용은 사업자 부담)"],
  ["M", "인력", "참여 인력은 정규직으로 구성해야 하고 보안서약서·건강보험납입증명서 제출이 필요하다.", "투입 인력의 정규직 여부와 재직 기간을 사전에 확인한다.", "계약업체는 사업 투입 시 대표자 및 참여인원 대상으로 보안서약서를 제출해야 함"],
  ["L", "계약", "지식재산권은 발주기관과 공동 소유가 원칙이나 세부사항은 협의로 정한다. 제안서 보상도 없다.", "기존 자산의 귀속 범위를 계약 단계에서 구분해 협의한다.", "지식재산권은 발주기관과 제안사(계약상대자)가 공동으로 소유함을 원칙으로 하되"],
  ["L", "일정", "1월 1일까지 계약이 체결되지 않으면 실제 개시일부터 일할 정산한다. 계약 후 10일 이내 제출물이 다수 겹친다.", "계약 후 10일 이내 제출 서류 목록을 착수 전에 준비한다.", "계약 후 10일 이내 제출"],
];

const EXECUTION_REQUESTS: [string, string][] = [
  ["성남 상주 인력 확보 방안", "성남 상주 요건을 충족할 협력사 인력 또는 원격·협의 방식이 필요해요."],
  ["협력사 활용 시 하도급·공동수급 구조", "하도급 50% 한도와 사전승인, 공동이행 지분(5% 이상) 조건 안에서 상주·현장 대응을 구성할 수 있는지 판단해야 해요."],
  ["성남 현장 2시간 도착 대응 체계", "지연 시 배상책임과 해지 사유가 되므로 성남 인근 대응 수단의 현실성을 확인해야 해요."],
  ["비용 부담 항목의 원가 반영", "만족도 조사 보상, SSL 갱신, 웹접근성 인증 갱신 비용이 사업금액에 포함되어 수익성에 영향을 줘요."],
  ["개편사업자 하자 연계 업무 수행 방안", "하자보수 기간이 2027.4에 종료되어 연계 업무와 종료 전 점검 책임이 수행 초기에 집중돼요."],
];

/** 원본 결과의 확인 요청 대부분은 배점 추정용 회사 필드 키다(시안 README "확인 요청 63건 중 58건"). */
const COMPANY_FIELDS = [
  "company.founded", "company.employees", "company.revenue_3y", "registrations.credit_rating.grade",
  "registrations.credit_rating.issued_at", "registrations.sme_certificate.status", "registrations.direct_production.items",
  "certifications.iso9001", "certifications.iso27001", "certifications.gs", "certifications.web_accessibility_mark",
  "staff.pm.years", "staff.pm.grade", "staff.pm.certificates", "staff.dev.count", "staff.dev.years", "staff.designer.years",
  "staff.publisher.years", "staff.dba.years", "staff.security.years", "staff.training.hours_3y", "staff.regular_ratio",
  "portfolio.homepage_maintenance.count_3y", "portfolio.homepage_maintenance.amount_max", "portfolio.public_web.count_5y",
  "portfolio.local_gov.count_5y", "portfolio.egov_framework.count", "portfolio.web_accessibility.count",
  "portfolio.sla_24h.count", "portfolio.remote_dev.count", "finance.debt_ratio", "finance.current_ratio",
  "finance.operating_margin", "office.locations", "office.seongnam_nearby", "partners.onsite_seongnam",
  "partners.commercial_sw_support", "quality.fp_expert", "quality.security_education", "quality.process_cert",
];

function analysisFixture(variant: "completed" | "partial"): EngineAnalysis {
  const partial = variant === "partial";
  const fits = FITS.map(([reqId, name, fit, portfolio, gap, quote], index) => {
    const unread = partial && PARTIAL_UNREAD.test(reqId);
    return {
      req_id: reqId,
      fit: unread ? "UNKNOWN" as const : fit,
      rationale: unread ? "원문의 이 범위를 읽지 못해 대조하지 않았어요. (예시)"
        : reqId === "MPR-003" ? "[[P2026-03-1]]의 현장 장애 대응 범위를 확인했어요." : RATIONALE[fit],
      evidence_portfolio_ids: unread ? [] : Array.from({ length: portfolio }, (_, n) => `P2026-${String(index + 1).padStart(2, "0")}-${n + 1}`),
      gap_action: unread ? null : gap || null,
      evidence: unread ? null : evidence(quote, partial ? 31 + index : null),
      // 원문에서 옮긴 요구사항 명칭(엔진 14756a0부터). 부분 결과 예시는 옛 응답처럼 필드가 없다.
      ...(partial ? {} : { name, definition: null, instance_key: null }),
    };
  });
  const gates: EngineAnalysis["gates"] = [
    ...(partial ? [{
      code: "PAST_PERFORMANCE",
      rule_text: "최근 3년 이내 단일 계약 2억 원 이상의 공공 홈페이지 유지관리 실적을 보유한 자",
      company_value: "해당 규모의 실적이 확인되지 않았어요 (예시)",
      verdict: "FAIL" as const,
      evidence: [evidence("최근 3년 이내 단일 계약 2억 원 이상의 공공 홈페이지 유지관리 실적", 12, "S004")],
      action: "실적증명서로 금액·기간 확인",
      unknown_fields: [],
    }] : []),
    {
      code: "ONSITE_LOCATION",
      rule_text: "웹개발&시스템관리자(상주 기술인력) 1명 상주: 성남시에서 제공하는 장소(상주 원칙, 협의 후 결정)",
      company_value: "성남 상주 가능 인원이 확인되지 않았어요 (예시)",
      verdict: "RISK",
      evidence: [evidence("참여인력은 성남시에서 제공하는 장소에서 상주하는 것을 원칙으로 하되", partial ? 44 : null, "S021")],
      action: "기타 상주 가능 인원 확인",
      unknown_fields: ["staff.onsite_seongnam.count"],
      input_fields: ["staff.onsite_seongnam"],
    },
    {
      code: "CONSORTIUM_CONDITION",
      rule_text: "공동수급 시 각 구성원은 입찰 참가자격 조건에 모두 해당",
      company_value: "원문 확인이 필요해요",
      verdict: "UNKNOWN",
      evidence: [evidence("공동수급 시 각 구성원은 입찰 참가자격 조건에 모두 해당", partial ? 9 : null, "S004")],
      action: "공고 원문 조항 확인",
      unknown_fields: ["notice.consortium_clause"],
    },
    ...([
      ["DEBARMENT", "부정당업자 입찰참가자격 제한에 해당되지 않는 업체", "제한 이력 없음 (예시)"],
      ["G2B_REGISTERED", "나라장터(G2B)에 소프트웨어 사업자로 입찰 참가자격 등록", "등록 (예시)"],
      ["INDUSTRY_CODE", "컴퓨터관련서비스사업(업종코드 1468) 등록", "1468 (예시)"],
      ["DIRECT_PRODUCTION", "직접생산확인증명서(정보시스템유지관리서비스) 소지", "소지 (예시)"],
      ["SME_CERT", "중·소기업·소상공인 확인서(공공기관 입찰용) 소지", "소지 (예시)"],
    ] as const).map(([code, rule, value]) => ({
      code,
      rule_text: rule,
      company_value: value,
      verdict: "PASS" as const,
      evidence: [evidence(rule, partial ? 8 : null, "S004")],
      action: null,
      unknown_fields: [],
    })),
  ];
  return {
    schema_version: 1,
    recommendation: partial
      ? { decision: "NO_GO", fit_score: 0, summary: "충족하지 못한 참가자격이 있어요. 부분 결과 기준이에요. (예시)", preconditions: [], why_not: ["단일 계약 2억 원 이상 실적 미확인 (예시)"] }
      : { decision: "CONDITIONAL_GO", fit_score: 0, summary: "미확인 자격 조건이 있어요. (예시)", preconditions: ["상주 가능 인원 확인 (예시)"], why_not: [RISKS[0][2], RISKS[2][2], RISKS[4][2]] },
    assessment: partial
      ? {
        state: "ready",
        decision: "NO_GO",
        reason_codes: ["hard_gate_fail"],
        score_interval: null,
        provisional: {
          decision: "NO_GO",
          basis: "confirmed",
          conditions: [{
            id: "recheck_fail:PAST_PERFORMANCE", kind: "recheck_fail", title: "공공 홈페이지 유지관리 실적",
            check: "실적증명서로 금액·기간 확인", if_not: "충족하지 못하면 참가 불가", gate_codes: ["PAST_PERFORMANCE"],
          }],
          fit_coverage: { judged: 29, total: 41 },
        },
      }
      : {
        state: "abstain",
        decision: null,
        reason_codes: ["unknown_gate"],
        score_interval: null,
        provisional: {
          decision: "CONDITIONAL_GO",
          basis: "assumed",
          conditions: [
            { id: "risk_gate:ONSITE_LOCATION", kind: "risk_gate", title: "상주 근무", check: "기타 상주 가능 인원 확인", if_not: "해결하지 못하면 포기 검토", gate_codes: ["ONSITE_LOCATION"] },
            { id: "unknown_gate:CONSORTIUM_CONDITION", kind: "unknown_gate", title: "원문 확인이 필요한 참가자격", check: "공고 원문 조항 확인", if_not: "충족하지 못하면 참가 불가", gate_codes: ["CONSORTIUM_CONDITION"] },
          ],
          demo_fields: ["staff.onsite_seongnam.count"],
          fit_coverage: { judged: 37, total: 41 },
        },
      },
    gates,
    fits,
    risks: RISKS.map(([severity, category, description, mitigation, quote], index) => ({
      category, severity, description, mitigation, evidence: evidence(quote, partial ? 50 + index : null, "S030"),
    })),
    data_to_confirm: COMPANY_FIELDS.map((field) => ({ field, why: "확인된 회사 근거 없음 (예시)" })),
    review_actions: {
      requests: [
        ...EXECUTION_REQUESTS.map(([title, why], index) => ({
          id: `execution:${index + 1}`, kind: "execution" as const, fields: [], title, why,
          affects: ["risks"], blocking: false, completion: "수행계획서에 반영",
          ...(partial ? {} : { purpose: "execution" as const, availability: null }),
        })),
        {
          id: "notice:consortium", kind: "notice" as const, fields: ["notice.consortium_clause"],
          title: "공동수급 구성원 자격 조항", why: "공동수급 시 구성원마다 참가자격을 모두 갖춰야 하는지 원문 조항을 확인해야 해요.",
          affects: ["gates.CONSORTIUM_CONDITION"], blocking: true, completion: "공고 원문 확인",
          ...(partial ? {} : { purpose: "decision" as const, availability: "awaiting_input" as const }),
        },
        // 추적 판단에 쓰이는 회사 확인(엔진 f69f8cf의 `purpose=decision`). 접지 않고 보인다.
        ...(partial ? [] : [{
          id: "company:decision:onsite", kind: "company" as const, fields: ["people.onsite_capacity"],
          title: "상주 가능 지역·인원", why: "상주 조건을 충족하는지 회사 기록으로 확인해야 해요. (예시)",
          affects: ["gates.ONSITE_LOCATION"], blocking: true, completion: "회사 근거 등록",
          purpose: "decision" as const, availability: "check_now" as const,
        }]),
        ...COMPANY_FIELDS.map((field) => ({
          // 완료 예시는 엔진이 붙인 읽을 수 있는 제목, 부분 결과 예시는 옛 응답의 필드 키 그대로다.
          id: `company:${field}`, kind: "company" as const, fields: [field], title: partial ? field : `회사 기록 확인 · ${field.split(".").at(-1)}`,
          why: "확인된 회사 근거가 없어요. (예시)", affects: ["scores"], blocking: false, completion: "회사 근거 등록",
          ...(partial ? {} : { purpose: "scoring" as const, availability: "check_now" as const }),
        })),
      ],
    },
    knowledge: { pages: ["onsite-staffing", "P2026-03-1"], skipped: ["security"] },
    citations: { total: 62, verified: 61, unverified: 1 },
    profitability: { budget_krw: 500_000_000, est_mm: null, note: "세부 투입 공수를 확인할 수 없어요." },
    facts: {
      project: {
        budget_krw: 500_000_000, vat_included: true, bidding_method: "제한경쟁", contract_method: "협상에 의한 계약",
        evidence: [evidence("사업 금액 500,000,000원(VAT 포함)", null)],
      },
      evaluation: {
        tech_weight: 90, price_weight: 10, qualifying_rule: "기술능력평가 점수 기준",
        evidence: [evidence("기술능력평가(90%)와 가격평가(10%)", null)],
      },
      staffing: [
        { role: "웹개발&시스템관리자", grade: null, count: 1, resident: true, location: "성남시 제공 장소(협의 후 결정)", min_years: 5, notes: "상주 기술인력", evidence: evidence("참여인력 중 상주 기술인력은 웹개발&시스템관리자로 1명 이상", partial ? 44 : null, "S021") },
        { role: "기획/분석", grade: "고급", count: null, resident: null, location: null, min_years: 7, notes: null, evidence: evidence("기획/분석 7년 이상", partial ? 45 : null, "S021") },
        { role: "웹디자인/퍼블리싱", grade: "중급", count: null, resident: null, location: null, min_years: 3, notes: null, evidence: evidence("웹디자인/퍼블리싱 3년 이상", partial ? 45 : null, "S021") },
      ],
      contract_terms: {
        subcontract: { allowed: true, limit_pct: 50, note: "사전승인 필요, 재하도급 불허" },
        consortium: { allowed: true, type: "공동이행", note: "5개 업체 이내, 구성원 지분 5% 이상" },
        ip_ownership: "발주기관과 공동 소유 원칙, 세부는 협의",
        sla: { has: true, penalty_note: "장애처리 지연 시 월 유지관리비에서 공제" },
        warranty_months: 12,
        proposal_compensation: null,
        proposal_page_limit: 100,
        remote_work: { allowed: null, note: "작업장소는 성남시 제공, 제안 장소는 검토 후 거부 가능" },
        evidence: [evidence("하도급은 사업금액의 50%를 초과할 수 없으며", partial ? 60 : null, "S032")],
      },
    },
    // 원문 요구사항 수와 한자·외국어 혼입 경고(엔진 14756a0부터). 부분 결과 예시는 옛 응답처럼 없다.
    ...(partial ? {} : {
      requirement_counts: { source_found: fits.length, analysis_input: fits.length, source_expected: null },
      language_warnings: [{ path: "risks[0].description", terms: ["納期"], retry_pass: "synth" as const }],
    }),
    // 검증된 인용의 원문 블록 위치(adapter.source_evidence). HWPX 블록에는 쪽이 없을 수 있다(`page: null`).
    source_evidence: fits.flatMap((fit, index) => fit.evidence ? [{
      evidence_path: `/fits/${index}/evidence`,
      document_version_id: DOCUMENT_VERSION_ID,
      source_sha256: SOURCE_SHA,
      block_key: `b${String(200 + index).padStart(4, "0")}`,
      page: partial ? 31 + index : null,
      start: 0,
      end: fit.evidence.quote.length,
      location_status: "exact" as const,
      basis: "cited_section" as const,
    }] : []),
  };
}

/** 분석 완료(b1)·부분 결과(b2) 엔진 run 예시. `companyId`는 화면의 회사 기준 응답과 같아야 한다. */
export function engineAnalysisRunFixture(variant: "completed" | "partial", companyId: string, noticeId: number): EngineRun {
  const partial = variant === "partial";
  return {
    id: partial ? "5f0b9a7e-2c1d-4e8f-9a6b-000000000b02" : "5f0b9a7e-2c1d-4e8f-9a6b-000000000b01",
    company_id: companyId,
    notice_id: noticeId,
    bundle_id: "e8ef5a2c-c5f5-4d9a-8d7d-5fef74955b33",
    request_id: partial ? "d7badcfb-5627-42ac-899c-0f1f1f95b002" : "d7badcfb-5627-42ac-899c-0f1f1f95b001",
    engine_version: "bid-deep-engine.v1",
    engine_sha256: "e".repeat(64),
    input_currentness: "current",
    profile_version_id: companyId,
    profile_sha256: "b".repeat(64),
    graph_version_id: companyId,
    graph_sha256: "c".repeat(64),
    documents: [{ document_version_id: DOCUMENT_VERSION_ID, source_sha256: SOURCE_SHA, structure_id: "f1e2d3c4-0000-4000-8000-000000000001", structure_sha256: "f".repeat(64) }],
    quality_status: "mock_reference",
    status: variant,
    created_at: "2026-11-21T01:10:00Z",
    started_at: "2026-11-21T01:10:05Z",
    completed_at: "2026-11-21T01:12:00Z",
    input_sha256: "a".repeat(64),
    error_code: null,
    warnings: partial ? ["structure_section_unreadable", "fits_partially_judged"] : [],
    analysis: analysisFixture(variant),
  };
}


export const analysisOverviewResult: OverviewRunResult = {
  business_overview: [
    { claim_id: "purpose", text: "사업 목적은 시청 홈페이지를 안정적으로 유지하고 시민에게 정확한 정보를 제공하는 것이에요.", evidence: [{ page: 3, quote: "시청 홈페이지를 안정적으로 유지" }] },
    { claim_id: "purpose2", text: "시민의 정보 접근성을 높이고 부서별 홈페이지 운영을 지원해요.", evidence: [{ page: 3, quote: "부서별 홈페이지 운영을 지원" }] },
    { claim_id: "background", text: "추진 배경은 2026년 홈페이지 개편 후의 연속 운영이에요.", evidence: [{ page: 4, quote: "2026년 홈페이지 개편 후의 연속 운영" }] },
  ],
  main_tasks: [
    "부서별 홈페이지 요청에 따라 기능을 개선하고 보안 점검과 업데이트를 지원해요.",
    "시민의 서비스 이용을 검증하고 사용자 만족도를 조사해요.",
    "홈페이지 장애에 신속히 대응하고 복구 작업 이력을 확인해요.",
    "유지관리 산출물을 최신화하고 사업자 간 인수인계를 지원해요.",
    "부서별 요청사항을 확인하고 운영 도구와 시스템을 개선해요.",
  ].map((text, i) => ({ claim_id: `task-${i}`, text, evidence: [{ page: 3, quote: text }] })),
  budget_and_period: [
    { claim_id: "amount", text: "사업 금액은 500,000,000원이에요.", evidence: [{ page: 3, quote: "사업 금액 500,000,000원(VAT 포함)" }] },
    { claim_id: "period", text: "사업 기간은 계약일부터 12개월이에요.", evidence: [{ page: 4, quote: "계약일부터 12개월" }] },
  ],
  input_limitations: ["3·4쪽의 본문 텍스트만 읽었어요."],
};

export const analysisWikiProject: WikiProject = {
  id: "P2026-03-1", title: "시민 서비스 운영 실적", client: "합성 발주기관",
  period_start: "2025-01", period_end: "2025-12", type: "유지관리", role: "주사업자",
  has_page: true, requirement_count: null, ingested: null, ingested_at: null, evidence_links: null,
};

export function analysisPageText(run: EngineRun, overviewId: string, pdfSha256: string): OverviewRunPageText {
  const pages = Array.from({ length: 64 }, (_, index) => ({ number: index + 1, display_page: null, text: "" }));
  const claims = [...analysisOverviewResult.business_overview, ...analysisOverviewResult.main_tasks, ...analysisOverviewResult.budget_and_period];
  for (const claim of claims) {
    for (const proof of claim.evidence) pages[proof.page - 1].text += `❍ ${proof.quote}\n`;
  }
  run.analysis?.fits.forEach((fit, index) => {
    if (fit.evidence) pages[11 + index].text += fit.evidence.quote;
  });
  return {
    schema: "bidops.prespec-overview-page-text.v1", run_id: overviewId, notice_id: run.notice_id,
    pdf_sha256: pdfSha256, document_version_id: DOCUMENT_VERSION_ID,
    page_count: pages.length, pages,
  };
}

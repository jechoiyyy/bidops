/**
 * RL-04 `/opportunities/:id/proposal` 제안서 탭용 고정 응답.
 *
 * 모양은 RL-04 spec "REST (`bidops.proposal.v1`)"의 `ProposalView`·`SectionView`·`Sentence`에서 옮겼다.
 * 값은 **fixture 작성자의 창작값**이며 실제 공고·회사·모델 출력이 아니다. 정책 id·모델명·hash·토큰 수는 일부러
 * 눈에 띄는 값(`PROPOSAL_FORBIDDEN_VALUES`)으로 두어 실무 화면 DOM에 새는지 검사할 수 있게 한다. 기대값은 화면
 * 코드를 가져오지 않고 값으로 직접 적는다.
 *
 * 완료 초안(`completedDraft()`)의 절별 구성(문장 17):
 *   overview        statement 2 · 요구사항 연결 없음
 *   track_record    statement 2 · placeholder 2("실적 금액·PM 경력"·"직접생산 세부품명")
 *   strategy        statement 1 · proposed_figure 1
 *   requirements    statement 3 · placeholder 1("SLA 월간 보고 양식") · proposed_figure 1 · 요구사항 7 연결
 *   operations_sla  statement 2
 *   organization    statement 1 · placeholder 1("투입 인력 수")
 * → 확인할 문장 = 빈 자리 4 + 제안 수치 2 = 6, 비어 있는 자리 4, 제안 수치 2. 요구사항 수행방안 탭 pill = 2.
 */
import type {
  ProposalDraft,
  ProposalParagraph,
  ProposalRequirementLink,
  ProposalSection,
  ProposalSectionKey,
  ProposalSentence,
  ProposalSource,
  ProposalView,
} from "../../src/lib/types";
import { POLICY_ID, POLICY_SHA, SOURCE_SHA, MODEL_NAME, sampleMatrix } from "./verdict";

export const PROPOSAL_DRAFT_ID = "d4000000-0000-4000-8000-000000000001";
export const PROPOSAL_OLD_DRAFT_ID = "d4000000-0000-4000-8000-000000000000";
export const PROPOSAL_EXPORT_ID = "e4000000-0000-4000-8000-000000000001";
export const PROPOSAL_PDF_SHA = "8".repeat(64);
export const PROPOSAL_INPUT_SHA = "6".repeat(64);

/** 제안서 탭 DOM에 없어야 하는 값들(정책 id·모델명·sha·토큰 수·참조 실행 원문 표식). */
export const PROPOSAL_FORBIDDEN_VALUES = [
  POLICY_ID,
  POLICY_SHA,
  SOURCE_SHA,
  PROPOSAL_PDF_SHA,
  PROPOSAL_INPUT_SHA,
  MODEL_NAME,
  "unmeasured_reference",
  "mock_reference",
  "proposal-policy-luna-v1",
  "prompt_tokens",
  "output_tokens",
];

export const SECTION_TITLES: Record<ProposalSectionKey, string> = {
  overview: "제안 개요",
  track_record: "사업수행 실적",
  strategy: "수행 전략",
  requirements: "요구사항 수행방안",
  operations_sla: "운영·SLA",
  organization: "수행조직",
};

const ORDER: ProposalSectionKey[] = ["overview", "track_record", "strategy", "requirements", "operations_sla", "organization"];

/** 문장 id(UUID). `n`은 절 안에서 유일하다. */
export function sentenceId(sectionIndex: number, n: number): string {
  return `5${sectionIndex}000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
}

function source(kind: ProposalSource["kind"], ref: string, quote: string): ProposalSource {
  return { kind, ref, quote };
}

function statement(id: string, text: string, sources: ProposalSource[]): ProposalSentence {
  return { sentence_id: id, text, kind: "statement", sources, placeholder_hint: null, edited: false };
}

function placeholder(id: string, text: string, hint: string): ProposalSentence {
  return { sentence_id: id, text, kind: "placeholder", sources: [], placeholder_hint: hint, edited: false };
}

function figure(id: string, text: string, sources: ProposalSource[]): ProposalSentence {
  return { sentence_id: id, text, kind: "proposed_figure", sources, placeholder_hint: null, edited: false };
}

function paragraph(id: string, heading: string | null, sentences: ProposalSentence[]): ProposalParagraph {
  return { paragraph_id: id, heading, sentences };
}

/** 판정 fixture(`sampleMatrix`)와 같은 unit id로 연결한다. 그래야 요구사항 문장·근거 라벨을 판정 표에서 읽는다. */
function link(matrixIndex: number, paragraphId: string): ProposalRequirementLink {
  const row = sampleMatrix()[matrixIndex];
  return { unit_id: row.unit_id, paragraph_id: paragraphId, fit_status: row.fit_status };
}

function section(
  key: ProposalSectionKey,
  status: ProposalSection["status"],
  paragraphs: ProposalParagraph[],
  links: ProposalRequirementLink[] = [],
  extra: Partial<ProposalSection> = {},
): ProposalSection {
  return {
    section_key: key,
    title: SECTION_TITLES[key],
    revision: 1,
    status,
    paragraphs,
    requirement_links: links,
    error_code: null,
    ...extra,
  };
}

const NOTICE_TITLE_QUOTE = "스마트 도시 통합플랫폼 고도화 사업";

/** 완료된 여섯 절(검토 전). 위 머리말의 구성이다. */
export function completedSections(): ProposalSection[] {
  const base = sampleMatrix();
  return [
    section("overview", "completed", [
      paragraph("o1", "사업 배경", [
        statement(sentenceId(0, 1), "본 사업은 스마트 도시 통합플랫폼을 고도화하여 시민 서비스를 개선하는 것을 목적으로 한다.", [
          source("notice_meta", "title", NOTICE_TITLE_QUOTE),
        ]),
        statement(sentenceId(0, 2), "발주기관은 클라우드 기반 통합 인증 체계의 제공을 요구한다.", [
          source("requirement_unit", base[0].unit_id, "통합 인증 체계를 제공하여야 한다."),
        ]),
      ]),
    ]),
    section("track_record", "completed", [
      paragraph("t1", "유사 사업 실적", [
        statement(sentenceId(1, 1), "회사는 홈페이지·포털 운영과 유지관리 분야에서 유사 사업을 수행해 왔다.", [
          source("company_fact", "project:homepage-ops", "민원·공모 홈서비스 유지관리"),
        ]),
        placeholder(sentenceId(1, 2), "대표 실적의 계약 금액과 PM 경력을 기재한다.", "실적 금액·PM 경력"),
      ]),
      paragraph("t2", "보유 인증", [
        statement(sentenceId(1, 3), "회사는 ISO 9001 품질경영 인증을 보유하고 있다.", [
          source("company_fact", "cert:iso9001", "ISO 9001"),
        ]),
        placeholder(sentenceId(1, 4), "직접생산 확인 세부 품명을 기재한다.", "직접생산 세부품명"),
      ]),
    ]),
    section("strategy", "completed", [
      paragraph("s1", "수행 전략", [
        statement(sentenceId(2, 1), "통합 인증 연계는 표준 프로토콜을 기반으로 설계한다.", [
          source("requirement_unit", base[0].unit_id, "통합 인증 체계를 제공하여야 한다."),
        ]),
        figure(sentenceId(2, 2), "화면 응답시간은 3초 이내를 목표로 한다.", [
          source("requirement_unit", base[3].unit_id, "장애 발생 시 30분 이내 대응"),
        ]),
      ]),
    ]),
    section(
      "requirements",
      "completed",
      [
        paragraph("r1", "통합 인증 체계", [
          statement(sentenceId(3, 1), "통합 인증 체계는 클라우드 기반으로 제공한다.", [
            source("requirement_unit", base[0].unit_id, "통합 인증 체계를 제공하여야 한다."),
          ]),
        ]),
        paragraph("r2", "상주 인력", [
          statement(sentenceId(3, 2), "정보보호 전문 인력의 상주 요건을 확인하여 대응한다.", [
            source("requirement_unit", base[1].unit_id, "정보보호 전문 인력 3명 이상 상주"),
            source("company_fact", "staff:onsite", "상주 인원"),
          ]),
          placeholder(sentenceId(3, 3), "상주 인력의 구성과 일정을 기재한다.", "SLA 월간 보고 양식"),
        ]),
        paragraph("r3", "장애 대응", [
          figure(sentenceId(3, 4), "장애 발생 시 30분 이내 대응 체계를 갖춘다.", [
            source("requirement_unit", base[3].unit_id, "장애 발생 시 30분 이내 대응"),
          ]),
          statement(sentenceId(3, 5), "직접생산 확인증명서 보유 여부는 발급기관 확인 뒤 기재한다.", [
            source("requirement_unit", base[2].unit_id, "직접생산 확인증명서 보유 업체"),
          ]),
        ]),
      ],
      [link(0, "r1"), link(1, "r2"), link(2, "r3"), link(3, "r3"), link(4, "r3"), link(5, "r1"), link(6, "r2")],
    ),
    section("operations_sla", "completed", [
      paragraph("p1", "운영·유지관리", [
        statement(sentenceId(4, 1), "운영 중 장애는 접수 즉시 등급별로 분류하여 대응한다.", [
          source("requirement_unit", base[3].unit_id, "장애 발생 시 30분 이내 대응"),
        ]),
        statement(sentenceId(4, 2), "개인정보 처리 시스템은 보안 인증 요건을 충족하도록 관리한다.", [
          source("requirement_unit", base[6].unit_id, "개인정보 처리 시스템은 보안 인증을"),
        ]),
      ]),
    ]),
    section("organization", "completed", [
      paragraph("g1", "수행조직", [
        statement(sentenceId(5, 1), "수행조직은 사업관리·개발·운영 역할로 구성한다.", [
          source("company_fact", "staff:design_publishing", "디자인·퍼블리싱"),
        ]),
        placeholder(sentenceId(5, 2), "이 사업에 투입할 인원 수를 기재한다.", "투입 인력 수"),
      ]),
    ]),
  ];
}

/** `counters`는 서버가 주는 값이다. fixture는 문장 구성에서 같은 규칙으로 만들어 서로 어긋나지 않게 한다. */
export function withCounters(draft: ProposalDraft): ProposalDraft {
  const sentences = draft.sections.flatMap((entry) => entry.paragraphs.flatMap((p) => p.sentences));
  const placeholders = sentences.filter((s) => s.kind === "placeholder").length;
  const figures = sentences.filter((s) => s.kind === "proposed_figure").length;
  return {
    ...draft,
    counters: {
      sentences_to_confirm: placeholders + figures,
      placeholders,
      proposed_figures: figures,
      reviewed_sections: draft.sections.filter((s) => s.status === "reviewed").length,
    },
  };
}

export function draftOf(
  sections: ProposalSection[],
  overrides: Partial<ProposalDraft> = {},
): ProposalDraft {
  const linked = new Set(sections.flatMap((s) => s.requirement_links.map((l) => l.unit_id)));
  return withCounters({
    draft_id: PROPOSAL_DRAFT_ID,
    status: "completed",
    stage: "draft",
    created_at: "2026-10-16T09:20:00+09:00",
    sections,
    requirement_coverage: { total: linked.size, linked: linked.size, unlinked_unit_ids: [] },
    counters: { sentences_to_confirm: 0, placeholders: 0, proposed_figures: 0, reviewed_sections: 0 },
    latest_export: null,
    quality_status: "unmeasured_reference",
    ...overrides,
  });
}

export function view(draft: ProposalDraft | null): ProposalView {
  return { schema_version: "bidops.proposal.v1", draft };
}

export function noneProposalView(): ProposalView {
  return view(null);
}

/** 여섯 절 모두 생성이 끝난 초안(검토 전). */
export function completedDraft(overrides: Partial<ProposalDraft> = {}): ProposalDraft {
  return draftOf(completedSections(), overrides);
}

/** 여섯 절 모두 검토 완료. 단계는 `reviewed`다. */
export function reviewedDraft(overrides: Partial<ProposalDraft> = {}): ProposalDraft {
  return draftOf(
    completedSections().map((entry) => ({ ...entry, status: "reviewed" as const })),
    { stage: "reviewed", ...overrides },
  );
}

/** 생성 중: overview 완료, track_record 생성 중, 나머지 대기. */
export function runningDraft(status: "queued" | "running" = "running"): ProposalDraft {
  const done = completedSections();
  if (status === "queued") {
    return draftOf(
      ORDER.map((key) => section(key, "queued", [])),
      { status: "queued", stage: "toc", quality_status: null },
    );
  }
  return draftOf(
    [
      done[0],
      section("track_record", "running", []),
      ...ORDER.slice(2).map((key) => section(key, "queued", [])),
    ],
    { status: "running", stage: "draft" },
  );
}

/** 일부 실패: operations_sla가 금지 내용 검증에서 실패. 나머지는 완료. */
export function partialDraft(errorCode = "proposal_forbidden_content"): ProposalDraft {
  return draftOf(
    completedSections().map((entry) =>
      entry.section_key === "operations_sla"
        ? { ...entry, status: "failed" as const, paragraphs: [], error_code: errorCode }
        : entry),
    { status: "partial" },
  );
}

/** 전체 실패: 여섯 절 모두 실패(알 수 없는 코드 하나 포함). */
export function failedDraft(): ProposalDraft {
  const codes: Record<ProposalSectionKey, string> = {
    overview: "proposal_section_invalid",
    track_record: "proposal_section_invalid",
    strategy: "proposal_review_timeout",
    requirements: "input_budget_exceeded",
    operations_sla: "proposal_coverage_incomplete",
    organization: "mystery_code_zz",
  };
  return draftOf(
    ORDER.map((key) => section(key, "failed", [], [], { error_code: codes[key] })),
    { status: "failed", stage: "toc" },
  );
}

/** 대체된 이전 초안(읽기 전용). */
export function supersededDraft(): ProposalDraft {
  return completedDraft({ draft_id: PROPOSAL_OLD_DRAFT_ID, status: "superseded" });
}

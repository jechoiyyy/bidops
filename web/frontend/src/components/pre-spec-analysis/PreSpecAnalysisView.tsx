/**
 * 사전규격 상세 `분석 완료` 화면(2026-11-21 시안 `docs/1121_prespec-detail/` b1~b3). **mock 빌드 전용이다.**
 *
 * `PreSpecDetailPage`가 `import.meta.env.BIDOPS_REVIEW_MOCK`일 때만 이 모듈을 `lazy`로 읽는다. 운영 빌드에서는 그
 * 상수가 `false`로 접혀 동적 import가 사라지므로, 이 파일의 코드·문구·CSS는 운영 번들에 들어가지 않는다(분석 엔진
 * mock 패널과 같은 경계, 설계고도화안 C-9). 엔진 경로는 mock_reference뿐이며 live 전송은 fail closed다.
 *
 * 화면은 엔진 run 응답의 `analysis`(원본 `bid_deep_engine.analysis.schemas.Analysis` + BidOps `source_evidence`)를
 * 건수로 세고 묶어 보일 뿐 값을 다시 계산하거나 문장을 만들지 않는다. 코드값은 한국어 이름으로 옮기고 모르는 코드는
 * 그대로 보인다. 점수(`fit_score`·`score_interval`·`scores`)와 입찰 준비 서류 목록은 그리지 않는다.
 */
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { PageHeaderTabs } from "../common/PageHeaderActions";
import { companyContextQueryKey, getCompanyContext } from "../../lib/companyApi";
import { engineApi, engineKeys, type EngineAnalysis, type EngineEvidence, type EngineRun } from "../../lib/engineApi";
import { formatDateTime } from "../../lib/format";
import { qualityStatusLabel } from "../../lib/qualityStatus";
import "../../styles/pre-spec-analysis.css";

type Tone = "err" | "warn" | "neutral" | "model";

function Tag({ label, tone = "neutral" }: { label: string; tone?: Tone }) {
  return <span className={`pa-tag is-${tone}`}>{label}</span>;
}

const GATE_VERDICT: Record<string, [string, Tone]> = {
  FAIL: ["차단", "err"], RISK: ["위험", "warn"], UNKNOWN: ["미확인", "warn"], PASS: ["충족", "neutral"],
};
const FIT_LABEL: Record<string, [string, Tone]> = {
  GAP: ["부족", "err"], UNKNOWN: ["미확인", "warn"], PARTIAL: ["부분", "warn"], FULL: ["충족", "neutral"],
};
const SEVERITY: Record<string, [string, Tone]> = { H: ["상", "err"], M: ["중", "warn"], L: ["하", "neutral"] };
const GATE_CODE_LABEL: Record<string, string> = {
  G2B_REGISTERED: "나라장터 등록", INDUSTRY_CODE: "업종 코드", SW_BUSINESS_REPORT: "SW사업자 신고", SME_CERT: "중소기업 확인",
  DIRECT_PRODUCTION: "직접생산 확인", LARGE_CORP_EXCLUDED: "대기업 참여 제한", MUTUAL_INVEST_GROUP_EXCLUDED: "상호출자제한 기업집단 제한",
  REGION_LIMIT: "지역 제한", DEBARMENT: "부정당업자 제재", TAX_DELINQUENCY: "세금 체납", PAST_PERFORMANCE: "수행 실적",
  REQUIRED_CERT: "필수 인증", OTHER: "기타 조건", STAFFING_CAPACITY: "인력 투입", ONSITE_LOCATION: "상주 장소",
  CONSORTIUM_CONDITION: "공동수급 조건", INSOLVENCY: "부도·파산",
};
const DECISION_LABEL: Record<string, string> = { GO: "참여 검토", CONDITIONAL_GO: "조건부 참여 검토", NO_GO: "참여 비권장" };
const REASON_LABEL: Record<string, string> = {
  legacy_metadata: "이전 형식 결과", stale_stage: "이전 입력 기준 단계", missing_stage: "빠진 단계", empty_requirements: "요구사항 없음",
  missing_fits: "요구사항 대응 없음", unknown_gate: "미확인 자격 조건", untrusted_company_input: "확인되지 않은 회사 입력",
  uncertain_fit_decision: "대응 판단 불확실", untrusted_failure: "확인되지 않은 실패", confirmation_outdated: "확인 기록이 오래됨",
  hard_gate_fail: "참가자격 차단", min_contract_fail: "최소 계약 조건 미충족",
};
const CONDITION_KIND_LABEL: Record<string, string> = {
  recheck_fail: "자격 조건 · 차단", risk_gate: "자격 조건 · 위험", unknown_gate: "자격 조건 · 미확인",
  requirements_missing: "요구사항 없음", fit_coverage: "판정 범위", pdf_numeric: "수치 확인", stale_analysis: "이전 입력 기준",
};
const RUN_STATUS_LABEL: Record<string, string> = { completed: "분석 완료", partial: "부분 결과" };
const label = (map: Record<string, string>, code: string) => map[code] ?? code;
const tone = (map: Record<string, [string, Tone]>, code: string): [string, Tone] => map[code] ?? [code, "neutral"];

/** 엔진 값 `unknown`은 미확인이다(값을 지어내지 않는다). 그 밖은 그대로다. */
function companyValue(value: string): string {
  return value.trim().toLowerCase() === "unknown" ? "미확인" : value;
}

/** 인용의 쪽: 인용 자체 → BidOps `source_evidence`의 같은 경로 → 없음. 쪽을 다른 값에서 추정하지 않는다. */
function evidencePage(analysis: EngineAnalysis, path: string, evidence: EngineEvidence | null | undefined): number | null {
  if (evidence?.page != null) return evidence.page;
  return analysis.source_evidence?.find((item) => item.evidence_path === path && item.page !== null)?.page ?? null;
}

function pageLabel(page: number | null, missing = "쪽 정보 없음"): string {
  return page === null ? missing : `${page}쪽`;
}

function yesNo(value: boolean | null | undefined, yes: string, no: string): string {
  return value === null || value === undefined ? "미확인" : value ? yes : no;
}

function joinFacts(parts: (string | null | undefined | false)[]): string {
  return parts.filter((part): part is string => typeof part === "string" && part.trim() !== "").join(" · ");
}

/** 지금 보이는 사전규격의 엔진 run을 읽어 분석 완료 화면을 그릴지 알린다. 엔진 mock 패널과 같은 query key다. */
export function PreSpecEngineAnalysisProbe({ noticeId, onChange }: { noticeId: number; onChange: (run: EngineRun | null) => void }) {
  const company = useQuery({ queryKey: companyContextQueryKey, queryFn: ({ signal }) => getCompanyContext({ signal }), retry: false });
  const companyId = company.data?.company.company_id ?? null;
  const list = useQuery({
    queryKey: engineKeys.list(companyId ?? "", noticeId),
    queryFn: ({ signal }) => engineApi.list(companyId as string, noticeId, { signal }),
    enabled: companyId !== null,
    retry: false,
    refetchInterval: (query) => query.state.data?.items.some((run) => run.status === "queued" || run.status === "running") ? 2500 : false,
  });
  const latestId = list.data?.items[0]?.id ?? null;
  const detail = useQuery({
    queryKey: engineKeys.detail(companyId ?? "", noticeId, latestId),
    queryFn: ({ signal }) => engineApi.get(latestId as string, { signal }),
    enabled: companyId !== null && latestId !== null,
    retry: false,
  });
  const run = detail.data;
  const usable = run !== undefined && run.company_id === companyId && run.notice_id === noticeId
    && (run.status === "completed" || run.status === "partial") && run.analysis !== null;
  useEffect(() => {
    onChange(usable ? run : null);
  }, [onChange, run, usable]);
  return null;
}

const FIT_FILTERS = [
  { key: "open", label: "부족·미확인", match: (fit: string) => fit === "GAP" || fit === "UNKNOWN" },
  { key: "PARTIAL", label: "부분", match: (fit: string) => fit === "PARTIAL" },
  { key: "FULL", label: "충족", match: (fit: string) => fit === "FULL" },
  { key: "all", label: "전체", match: () => true },
] as const;
const FIT_ORDER = ["GAP", "UNKNOWN", "PARTIAL", "FULL"];
const GATE_ORDER = ["FAIL", "RISK", "UNKNOWN"];

function useWide(min: number): boolean {
  const [wide, setWide] = useState(() => window.innerWidth >= min);
  useEffect(() => {
    const onResize = () => setWide(window.innerWidth >= min);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [min]);
  return wide;
}

/**
 * 분석 완료 화면의 구역 2~7(요약 · 차단·자격 조건 · 확인할 일 · 요구사항 대응 · 리스크 · 인력·계약 조건)과 헤더 탭
 * 자리의 구역 이동 링크. 사실 줄·개요·원문·처리 상태 구역과 하단 결정 띠는 상세 페이지가 그린다.
 */
export function PreSpecAnalysisSections({ run }: { run: EngineRun }) {
  const analysis = run.analysis as EngineAnalysis;
  const partial = run.status === "partial";
  const gates = analysis.gates;
  const fits = analysis.fits;
  const risks = analysis.risks ?? [];
  const provisional = analysis.assessment?.provisional ?? null;
  const conditions = provisional?.conditions ?? [];
  const requests = analysis.review_actions?.requests ?? [];
  const planRequests = requests.filter((request) => request.kind === "execution" || request.kind === "notice");
  const companyRequests = requests.filter((request) => request.kind === "company");
  const coverage = provisional?.fit_coverage ?? null;

  const gateCount = (verdict: string) => gates.filter((gate) => gate.verdict === verdict).length;
  const fitCount = (fit: string) => fits.filter((item) => item.fit === fit).length;
  const riskCount = (severity: string) => risks.filter((risk) => risk.severity === severity).length;

  const [activeSection, setActiveSection] = useState("pa-summary");
  const [filter, setFilter] = useState<(typeof FIT_FILTERS)[number]["key"]>("open");
  const [selected, setSelected] = useState<string | null>(null);
  const wide = useWide(1400);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const openerRef = useRef<string | null>(null);

  const close = useCallback(() => {
    const opener = openerRef.current;
    setSelected(null);
    // 초점은 근거를 연 단추로 돌아간다.
    window.requestAnimationFrame(() => {
      if (opener) document.querySelector<HTMLButtonElement>(`[data-pa-ev="${CSS.escape(opener)}"]`)?.focus();
    });
  }, []);
  useEffect(() => {
    if (selected === null) return undefined;
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [close, selected]);

  const fitRows = useMemo(() => {
    const match = FIT_FILTERS.find((item) => item.key === filter)?.match ?? (() => true);
    return fits
      .map((fit, index) => ({ fit, index }))
      .filter(({ fit }) => match(fit.fit))
      .sort((left, right) => FIT_ORDER.indexOf(left.fit.fit) - FIT_ORDER.indexOf(right.fit.fit));
  }, [filter, fits]);

  const selectedRow = selected === null ? null : fits.map((fit, index) => ({ fit, index })).find(({ fit }) => fit.req_id === selected) ?? null;
  const sideOpen = selectedRow !== null && wide;
  const drawerOpen = selectedRow !== null && !wide;

  const sectionLinks: [string, string, number | null][] = [
    ["pa-summary", "요약", null],
    ["pa-gates", "자격 조건", gates.length],
    ["pa-todos", "확인할 일", conditions.length + planRequests.length],
    ["pa-reqs", "요구사항", fits.length],
    ["pa-risks", "리스크", risks.length],
    ["pa-terms", "인력·계약", null],
    ["ps-evidence", "원문", null],
  ];

  const opinionLine = (() => {
    const assessment = analysis.assessment;
    if (assessment === null) return <p className="pa-opinion-line">엔진 판단 표식 없음</p>;
    if (assessment.state === "abstain") {
      return (
        <p className="pa-opinion-line">
          <strong>판단 보류</strong>
          {provisional ? <> · 잠정 의견 <strong>{label(DECISION_LABEL, provisional.decision)}</strong></> : null}
        </p>
      );
    }
    return <p className="pa-opinion-line"><strong>{assessment.decision ? label(DECISION_LABEL, assessment.decision) : "판단 미확인"}</strong></p>;
  })();

  const evidencePanel = (mode: "side" | "drawer") => {
    if (!selectedRow) return null;
    const { fit, index } = selectedRow;
    const [fitText, fitTone] = tone(FIT_LABEL, fit.fit);
    const page = evidencePage(analysis, `/fits/${index}/evidence`, fit.evidence);
    const portfolio = fit.evidence_portfolio_ids;
    return (
      <aside className={`pa-ev is-${mode}`} aria-label={`${fit.req_id} 근거`} id="pa-ev">
        <div className="pa-ev-head">
          <strong>{fit.req_id}</strong>
          <button className="pa-btn" type="button" onClick={close} ref={closeRef}>닫기</button>
        </div>
        <p><Tag label={fitText} tone={fitTone} /></p>
        <h4>원문 발췌</h4>
        {fit.evidence ? <blockquote>{fit.evidence.quote}</blockquote> : <p className="pa-muted">연결된 원문 근거가 없어요.</p>}
        <p className="pa-cap">
          {joinFacts([
            pageLabel(page),
            fit.evidence ? (fit.evidence.verified === null ? "인용 검증 대기" : fit.evidence.verified ? "인용 검증됨" : "인용 검증 실패") : null,
          ])}
        </p>
        <h4>판단 사유</h4>
        <p>{fit.rationale.trim() || "미확인"}</p>
        <h4>회사 근거</h4>
        <p>{portfolio === undefined ? "미확인" : portfolio.length > 0 ? `회사 실적 ${portfolio.length}건` : "연결된 회사 근거가 없어요"}</p>
        {fit.gap_action ? <><h4>부족을 메우려면</h4><p>{fit.gap_action}</p></> : null}
      </aside>
    );
  };

  const drawerHost = drawerOpen ? document.querySelector<HTMLElement>(".app-content") : null;
  const footerHeight = drawerOpen ? document.getElementById("page-footer")?.offsetHeight ?? 0 : 0;

  const fitTable = (
    <table className="pa-table pa-req-table">
      <thead>
        <tr>
          <th scope="col" className="pa-col-id">요구 ID</th>
          <th scope="col">원문 발췌</th>
          <th scope="col" className="pa-col-tag">대응</th>
          {sideOpen ? null : <th scope="col" className="pa-col-company">회사 근거</th>}
          {sideOpen ? null : <th scope="col" className="pa-col-gap">부족을 메우려면</th>}
          <th scope="col" className="pa-col-end">원문</th>
        </tr>
      </thead>
      <tbody>
        {fitRows.map(({ fit, index }) => {
          const [fitText, fitTone] = tone(FIT_LABEL, fit.fit);
          const page = evidencePage(analysis, `/fits/${index}/evidence`, fit.evidence);
          const portfolio = fit.evidence_portfolio_ids;
          return (
            <tr key={`${index}:${fit.req_id}`} className={fit.req_id === selected ? "is-selected" : undefined}>
              <td className="pa-col-id">{fit.req_id}</td>
              <td className="pa-quote">{fit.evidence?.quote ?? <span className="pa-muted">원문 발췌 없음</span>}</td>
              <td><Tag label={fitText} tone={fitTone} /></td>
              {sideOpen ? null : <td>{portfolio === undefined ? <span className="pa-muted">미확인</span> : portfolio.length ? `회사 실적 ${portfolio.length}건` : <span className="pa-muted">근거 없음</span>}</td>}
              {sideOpen ? null : <td>{fit.gap_action ?? <span className="pa-muted">—</span>}</td>}
              <td className="pa-col-end">
                <button
                  className="pa-link"
                  type="button"
                  data-pa-ev={fit.req_id}
                  aria-expanded={fit.req_id === selected}
                  aria-controls={fit.req_id === selected ? "pa-ev" : undefined}
                  onClick={() => {
                    if (fit.req_id === selected) { close(); return; }
                    openerRef.current = fit.req_id;
                    setSelected(fit.req_id);
                  }}
                >
                  {page === null ? "근거 보기" : `${page}쪽`}
                </button>
              </td>
            </tr>
          );
        })}
        {fitRows.length === 0 ? <tr><td colSpan={sideOpen ? 4 : 6} className="pa-muted">이 보기에 해당하는 요구사항이 없어요.</td></tr> : null}
      </tbody>
    </table>
  );

  const staffing = analysis.facts?.staffing;
  const terms = analysis.facts?.contract_terms;
  const highRisks = risks.filter((risk) => risk.severity === "H");
  const otherRisks = [...risks.filter((risk) => risk.severity === "M"), ...risks.filter((risk) => risk.severity === "L")];
  const riskRow = (risk: (typeof risks)[number], key: number) => {
    const [text, riskTone] = tone(SEVERITY, risk.severity);
    return (
      <tr key={key}>
        <td className="pa-col-tag"><Tag label={text} tone={riskTone} /></td>
        <td className="pa-col-category">{risk.category}</td>
        <td>{risk.description}</td>
        <td className="pa-col-gap">{risk.mitigation ?? <span className="pa-muted">미확인</span>}</td>
      </tr>
    );
  };
  const blockingGates = gates.map((gate, index) => ({ gate, index }))
    .filter(({ gate }) => gate.verdict !== "PASS")
    .sort((left, right) => {
      const a = GATE_ORDER.indexOf(left.gate.verdict);
      const b = GATE_ORDER.indexOf(right.gate.verdict);
      return (a === -1 ? GATE_ORDER.length : a) - (b === -1 ? GATE_ORDER.length : b);
    });
  const passGates = gates.map((gate, index) => ({ gate, index })).filter(({ gate }) => gate.verdict === "PASS");
  const gateRow = ({ gate, index }: { gate: (typeof gates)[number]; index: number }) => {
    const [text, gateTone] = tone(GATE_VERDICT, gate.verdict);
    const page = evidencePage(analysis, `/gates/${index}/evidence/0`, gate.evidence[0]);
    return (
      <tr key={`${index}:${gate.code}`}>
        <td className="pa-col-tag"><Tag label={text} tone={gateTone} /></td>
        <td>{gate.rule_text}<span className="pa-sub">{label(GATE_CODE_LABEL, gate.code)}</span></td>
        <td className="pa-col-company-wide">
          {companyValue(gate.company_value)}
          {gate.action ? <span className="pa-sub">할 일 · {gate.action}</span> : null}
        </td>
        <td className="pa-col-end">{gate.evidence.length === 0 ? <span className="pa-muted">원문 근거 없음</span> : pageLabel(page)}</td>
      </tr>
    );
  };

  return (
    <>
      <PageHeaderTabs>
        <nav className="pa-section-nav" aria-label="구역 이동">
          {sectionLinks.map(([id, name, count]) => (
            <a
              key={id}
              href={`#${id}`}
              aria-current={activeSection === id ? "true" : undefined}
              onClick={() => setActiveSection(id)}
            >
              {name}{count !== null ? <span className="pa-section-nav-count">{count}</span> : null}
            </a>
          ))}
        </nav>
      </PageHeaderTabs>

      {/* 2. 분석 결과 요약 */}
      <section id="pa-summary" className="ps-card ps-sec pa-sec" aria-labelledby="pa-summary-title">
        <div className="ps-sec-head">
          <h2 id="pa-summary-title" className="ps-h-sec">분석 결과 요약</h2>
          <p className="pa-sec-meta">
            {joinFacts([
              label(RUN_STATUS_LABEL, run.status),
              formatDateTime(run.completed_at ?? run.created_at),
              run.input_currentness === "stale" ? "입력이 바뀐 과거 결과" : run.input_currentness === "unknown" ? "입력 현재성 확인 불가" : null,
            ])}
          </p>
        </div>
        {partial ? (
          <p className="pa-notice" role="note">
            <span>
              {joinFacts([
                "부분 결과예요",
                coverage ? `요구사항 ${coverage.total}건 중 ${coverage.judged}건 판정` : "판정 범위 미확인",
                run.warnings.length ? `실행 경고 ${run.warnings.join(", ")}` : null,
              ])}
            </span>
            <a href="#pa-reqs">요구사항 보기</a>
          </p>
        ) : null}
        <div className="pa-summary-grid">
          <dl className="pa-counts">
            <dt>자격 조건 {gates.length}</dt>
            <dd><Count label="차단" count={gateCount("FAIL")} href="#pa-gates" /><Count label="위험" count={gateCount("RISK")} href="#pa-gates" /><Count label="미확인" count={gateCount("UNKNOWN")} href="#pa-gates" /><Count label="충족" count={gateCount("PASS")} /></dd>
            <dt>요구사항 {fits.length}</dt>
            <dd><Count label="부족" count={fitCount("GAP")} href="#pa-reqs" /><Count label="미확인" count={fitCount("UNKNOWN")} href="#pa-reqs" /><Count label="부분" count={fitCount("PARTIAL")} href="#pa-reqs" /><Count label="충족" count={fitCount("FULL")} /></dd>
            <dt>리스크 {risks.length}</dt>
            <dd><Count label="상" count={riskCount("H")} href="#pa-risks" /><Count label="중" count={riskCount("M")} /><Count label="하" count={riskCount("L")} /></dd>
          </dl>
          <div className="pa-opinion">
            <Tag label="엔진 참고 의견" tone="model" />
            {opinionLine}
            {analysis.assessment?.reason_codes.length ? (
              <p className="pa-cap">판단 사유 · {analysis.assessment.reason_codes.map((code) => label(REASON_LABEL, code)).join(" · ")}</p>
            ) : null}
            {gateCount("FAIL") > 0 ? (
              <p className="pa-opinion-link"><a href="#pa-gates">차단 조건 {gateCount("FAIL")}건 보기</a></p>
            ) : conditions.length > 0 ? (
              <p className="pa-opinion-link"><a href="#pa-todos">추적 판단을 바꾸는 확인 {conditions.length}건 보기</a></p>
            ) : null}
            <p className="pa-cap">참고 의견이에요. 입찰 참여는 최종 Go/No-Go에서 정해요.</p>
          </div>
        </div>
        <p className="pa-basis">
          <span>
            {joinFacts([
              "분석 기준",
              `문서 ${run.documents.length}건`,
              coverage ? `요구사항 ${coverage.total}건 중 ${coverage.judged}건 판정` : "판정 범위 미확인",
              run.engine_version,
            ])}
          </span>
          {/* 품질 표식은 반드시 보인다 — mock 참조는 운영 결과·품질 근거가 아니다. */}
          <Tag label={qualityStatusLabel(run.quality_status)} />
        </p>
      </section>

      {/* 3. 차단·자격 조건 */}
      <section id="pa-gates" className="ps-card ps-sec pa-sec" aria-labelledby="pa-gates-title">
        <div className="ps-sec-head">
          <h2 id="pa-gates-title" className="ps-h-sec">차단·자격 조건 <span className="ps-cnt">{gates.length}건</span></h2>
          <p className="pa-sec-meta">차단 → 위험 → 미확인 순</p>
        </div>
        {blockingGates.length > 0 ? (
          <table className="pa-table">
            <thead><tr><th scope="col" className="pa-col-tag">판정</th><th scope="col">공고 조건</th><th scope="col" className="pa-col-company-wide">회사 확인 · 할 일</th><th scope="col" className="pa-col-end">원문</th></tr></thead>
            <tbody>{blockingGates.map(gateRow)}</tbody>
          </table>
        ) : <p className="pa-muted">차단·위험·미확인 자격 조건이 없어요.</p>}
        {passGates.length > 0 ? (
          <details className="pa-fold">
            <summary>충족 {passGates.length}건 보기</summary>
            <table className="pa-table"><tbody>{passGates.map(gateRow)}</tbody></table>
          </details>
        ) : null}
      </section>

      {/* 4. 확인할 일 */}
      <section id="pa-todos" className="ps-card ps-sec pa-sec" aria-labelledby="pa-todos-title">
        <div className="ps-sec-head">
          <h2 id="pa-todos-title" className="ps-h-sec">확인할 일 <span className="ps-cnt">{conditions.length + planRequests.length}건</span></h2>
          <p className="pa-sec-meta">추적 판단에 영향을 주는 것부터</p>
        </div>
        <h3 className="pa-sub-title">추적 판단을 바꾸는 확인 {conditions.length}건</h3>
        {conditions.length > 0 ? (
          <table className="pa-table">
            <tbody>
              {conditions.map((condition) => (
                <tr key={condition.id}>
                  <td className="pa-col-title"><strong>{condition.title}</strong><span className="pa-sub">{label(CONDITION_KIND_LABEL, condition.kind)}</span></td>
                  <td>{condition.check}<span className="pa-sub">안 되면 · {condition.if_not}</span></td>
                  <td className="pa-col-end">{condition.gate_codes.length > 0 ? <a href="#pa-gates">조건 보기</a> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="pa-muted">엔진 결과에 잠정 의견을 바꾸는 확인이 없어요.</p>}
        <h3 className="pa-sub-title">수행 방안 확인 {planRequests.length}건</h3>
        {planRequests.length > 0 ? (
          <table className="pa-table">
            <tbody>
              {planRequests.map((request) => (
                <tr key={request.id}>
                  <td className="pa-col-title"><strong>{request.title}</strong>{request.kind === "notice" ? <span className="pa-sub">공고 원문 확인</span> : null}</td>
                  <td>{request.why}</td>
                  <td className="pa-col-end">{request.blocking ? <Tag label="결정 전 확인" tone="warn" /> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="pa-muted">수행 방안 확인 요청이 없어요.</p>}
        {companyRequests.length > 0 ? (
          <details className="pa-fold">
            <summary>회사 자료 확인 {companyRequests.length}건 보기</summary>
            <ul className="pa-field-list">
              {companyRequests.map((request) => <li key={request.id}><code>{request.title}</code></li>)}
            </ul>
          </details>
        ) : null}
      </section>

      {/* 5. 요구사항 대응 */}
      <section id="pa-reqs" className="ps-card ps-sec pa-sec" aria-labelledby="pa-reqs-title">
        <div className="ps-sec-head">
          <h2 id="pa-reqs-title" className="ps-h-sec">요구사항 대응 <span className="ps-cnt">{fits.length}건</span></h2>
          <div className="pa-pills" role="group" aria-label="대응 상태">
            {FIT_FILTERS.map((item) => (
              <button
                key={item.key}
                type="button"
                aria-pressed={filter === item.key}
                onClick={() => setFilter(item.key)}
              >
                {item.label} {fits.filter((fit) => item.match(fit.fit)).length}
              </button>
            ))}
          </div>
        </div>
        <div className={`pa-req-layout${sideOpen ? " is-open" : ""}`}>
          <div className="pa-req-table-wrap">{fitTable}</div>
          {sideOpen ? evidencePanel("side") : null}
        </div>
        {/* 원본 Analysis의 요구사항 대응에는 요구사항 이름·필수 여부가 없다. 지어내지 않고 그 사실을 적는다. */}
        <p className="pa-cap">엔진 결과에 요구사항 이름과 필수 여부가 없어 원문 발췌로 요구를 보여요.</p>
        {drawerHost ? createPortal(
          <div className="pa-ev-drawer" style={{ bottom: footerHeight }}>{evidencePanel("drawer")}</div>,
          drawerHost,
        ) : null}
      </section>

      {/* 6. 리스크 */}
      <section id="pa-risks" className="ps-card ps-sec pa-sec" aria-labelledby="pa-risks-title">
        <div className="ps-sec-head">
          <h2 id="pa-risks-title" className="ps-h-sec">리스크 <span className="ps-cnt">{risks.length}건</span></h2>
          <p className="pa-sec-meta">심각도 상 → 하</p>
        </div>
        {risks.length === 0 ? <p className="pa-muted">엔진 결과에 리스크가 없어요.</p> : (
          <>
            {highRisks.length > 0 ? (
              <table className="pa-table">
                <thead><tr><th scope="col" className="pa-col-tag">심각도</th><th scope="col" className="pa-col-category">분류</th><th scope="col">내용</th><th scope="col" className="pa-col-gap">대응 방안</th></tr></thead>
                <tbody>{highRisks.map(riskRow)}</tbody>
              </table>
            ) : <p className="pa-muted">심각도 상 리스크 0건</p>}
            {otherRisks.length > 0 ? (
              <details className="pa-fold">
                <summary>중 {riskCount("M")}건, 하 {riskCount("L")}건 보기</summary>
                <table className="pa-table"><tbody>{otherRisks.map(riskRow)}</tbody></table>
              </details>
            ) : null}
          </>
        )}
      </section>

      {/* 7. 인력·계약 조건 */}
      <section id="pa-terms" className="ps-card ps-sec pa-sec" aria-labelledby="pa-terms-title">
        <div className="ps-sec-head">
          <h2 id="pa-terms-title" className="ps-h-sec">인력·계약 조건</h2>
          <p className="pa-sec-meta">원문에 없는 값은 미확인으로 표시</p>
        </div>
        <div className="pa-two-col">
          {staffing && staffing.length > 0 ? (
            <table className="pa-table">
              <thead><tr><th scope="col">역할</th><th scope="col">등급</th><th scope="col">인원</th><th scope="col">상주</th><th scope="col">경력</th></tr></thead>
              <tbody>
                {staffing.map((item, index) => (
                  <tr key={`${index}:${item.role}`}>
                    <td>{item.role}{item.location ? <span className="pa-sub">장소 · {item.location}</span> : null}</td>
                    <td>{item.grade ?? <span className="pa-muted">미확인</span>}</td>
                    <td>{item.count === null ? <span className="pa-muted">미확인</span> : `${item.count}명`}</td>
                    <td>{item.resident === null ? <span className="pa-muted">미확인</span> : item.resident ? "상주" : "비상주"}</td>
                    <td>{item.min_years === null ? <span className="pa-muted">미확인</span> : `${item.min_years}년 이상`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="pa-muted">인력 요구 미확인</p>}
          {terms ? (
            <dl className="pa-terms">
              <dt>하도급</dt><dd>{joinFacts([yesNo(terms.subcontract.allowed, "가능", "불가"), terms.subcontract.limit_pct === null ? null : `사업금액의 ${terms.subcontract.limit_pct}% 이내`, terms.subcontract.note])}</dd>
              <dt>공동수급</dt><dd>{joinFacts([yesNo(terms.consortium.allowed, "가능", "불가"), terms.consortium.type, terms.consortium.note])}</dd>
              <dt>지연배상</dt><dd>{joinFacts([yesNo(terms.sla.has, "있음", "없음"), terms.sla.penalty_note])}</dd>
              <dt>하자보수</dt><dd>{terms.warranty_months === null ? <span className="pa-muted">미확인</span> : `${terms.warranty_months}개월`}</dd>
              <dt>지식재산권</dt><dd>{terms.ip_ownership ?? <span className="pa-muted">미확인</span>}</dd>
              <dt>제안서 보상</dt><dd>{terms.proposal_compensation ?? <span className="pa-muted">미확인</span>}</dd>
              <dt>원격 근무</dt><dd>{joinFacts([yesNo(terms.remote_work.allowed, "가능", "불가"), terms.remote_work.note])}</dd>
            </dl>
          ) : <p className="pa-muted">계약 조건 미확인</p>}
        </div>
      </section>
    </>
  );
}

/** 건수 한 칸. 0건은 흐리게 두고 링크를 걸지 않는다. */
function Count({ label: name, count, href }: { label: string; count: number; href?: string }): ReactNode {
  const body = <>{name} {count}</>;
  return (
    <span className={`pa-count${count === 0 ? " is-zero" : ""}`}>
      {count > 0 && href ? <a href={href}><strong>{body}</strong></a> : body}
    </span>
  );
}

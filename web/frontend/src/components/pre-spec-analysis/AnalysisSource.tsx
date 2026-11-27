import type { ReactNode } from "react";
import type { WikiProject } from "../../lib/companyWikiApi";
import type { EngineAnalysis, EngineEvidence, EngineRun } from "../../lib/engineApi";
import type { EngineReviewResult } from "../../lib/engineReviewApi";
import type { PdfQuoteLocation } from "../../lib/pdfQuoteLocator";
import { qualityStatusLabel } from "../../lib/qualityStatus";
import type { NoticeDetailResponse, PageOverviewFact, PageOverviewView } from "../../lib/types";
import { analysisDate, isOutsideWorkUnits, knowledgeName, knowledgeReadNotice, known, workUnitsNotice } from "./analysisPresentation";

export type PageLink = (evidence: EngineEvidence | null | undefined, label: string) => ReactNode;

const gateNames: Record<string, string> = {
  G2B_REGISTERED: "나라장터 등록", DEBARMENT: "부정당업자 제재", SW_BUSINESS_REPORT: "SW사업자 신고",
  SME_CERT: "중소기업 확인", LARGE_CORP_EXCLUDED: "대기업 참여 제한",
  MUTUAL_INVEST_GROUP_EXCLUDED: "상호출자제한 기업집단 제한", DIRECT_PRODUCTION: "직접생산 확인",
};
const verdicts = { PASS: ["충족", "paw-ok"], FAIL: ["차단", "paw-err"], RISK: ["위험", "paw-warn"], UNKNOWN: ["미확인", "paw-warn"] };
const overviewWarnings: Record<string, string> = {
  quantity_mismatch: "개요 문장에 있는 숫자 가운데 함께 붙인 원문 인용에서 같은 숫자를 찾지 못한 것이 있어요.",
  quantity_metadata_mismatch: "모델이 문장과 따로 적어 낸 숫자 목록이 문장 속 숫자와 맞지 않아요.",
  quantity_relation_ambiguous: "어떤 숫자가 금액인지 기간인지, 부가세가 포함됐는지 등을 자동 검사가 확실히 가리지 못했어요.",
};

function allowed(value: boolean | null | undefined, note: string | null | undefined) {
  return [value == null ? "미확인" : value ? "허용" : "불허", note].filter(Boolean).join(" · ");
}

function sameFieldPrefix(left: string, right: string) {
  return left === right || left.startsWith(`${right}.`) || left.startsWith(`${right}[`)
    || right.startsWith(`${left}.`) || right.startsWith(`${left}[`);
}

function contractRows(analysis: EngineAnalysis) {
  const project = analysis.facts?.project;
  const evaluation = analysis.facts?.evaluation;
  const terms = analysis.facts?.contract_terms;
  const termQuote = (re: RegExp) => terms?.evidence.find(({ quote }) => re.test(quote));
  return [
    { name: "입찰·계약 방식", value: `${known(project?.bidding_method?.split(";")[0])} · ${known(project?.contract_method)}` },
    { name: "평가 배점", value: `기술 ${evaluation?.tech_weight ?? "미확인"} : 가격 ${evaluation?.price_weight ?? "미확인"} · ${known(evaluation?.qualifying_rule)}`,
      evidence: evaluation?.evidence.find(({ quote }) => /기술능력평가\s*\(|기술.{0,20}\d+\s*%/.test(quote)) },
    { name: "하도급", value: allowed(terms?.subcontract.allowed, terms?.subcontract.note), evidence: termQuote(/하도급/) },
    { name: "공동수급", value: allowed(terms?.consortium.allowed, terms?.consortium.note), evidence: termQuote(/공동수급체는|공동수급/) },
    { name: "원격 근무", value: allowed(terms?.remote_work.allowed, terms?.remote_work.note) },
    { name: "하자담보", value: terms?.warranty_months == null ? "미확인" : `${terms.warranty_months}개월`, evidence: termQuote(/하자담보/) },
    { name: "제안서 분량", value: terms?.proposal_page_limit == null ? "미확인" : `엔진 추출 값 ${terms.proposal_page_limit} · 단위·조건은 원문 확인` },
    { name: "지식재산권", value: known(terms?.ip_ownership), evidence: termQuote(/지식재산권은|지식재산권/) },
  ];
}

export function AnalysisTerms({ analysis, pageLink, consortiumIssue, openIssue }: {
  analysis: EngineAnalysis;
  pageLink: PageLink;
  consortiumIssue?: number;
  openIssue: (index: number) => void;
}) {
  const demo = analysis.assessment?.provisional?.demo_fields;
  const gates = analysis.gates;
  const count = (verdict: keyof typeof verdicts) => gates.filter((gate) => gate.verdict === verdict).length;
  return <section className="paw-blk" id="s-terms" aria-label="자격·계약">
    <div className="paw-blk-h"><h2>자격·계약 조건</h2>
      <span className="paw-aside">참가 자격 {gates.length}건 중 충족 {count("PASS")}건 · 차단 {count("FAIL")}건 · 위험 {count("RISK")}건 · 미확인 {count("UNKNOWN")}건</span></div>
    <div className="paw-cols2">
      <div>
        <h3 className="paw-sub">참가 자격 (엔진 결정적 판정)</h3>
        <table className="paw-plain"><tbody>{gates.map((gate, i) => {
          const [label, tone] = verdicts[gate.verdict];
          const demoRow = gate.input_fields?.some((field) => demo?.some((path) => sameFieldPrefix(field, path)));
          return <tr key={i}><th scope="row">{gateNames[gate.code] ?? gate.code}</th><td>
            <span className={`paw-chip ${tone}`}>{label}</span>{" "}
            {gate.evidence.length > 0 ? gate.evidence.map((evidence, j) => <span key={j}>{j > 0 && " "}{pageLink(evidence, "참가 자격 원문")}</span>)
              : pageLink(null, "참가 자격 원문")}
            {demoRow && <> <span className="paw-chip">데모 입력</span></>}
            <div className="paw-gate-rule" title={gate.rule_text}>{gate.rule_text.length > 90 ? `${gate.rule_text.slice(0, 90)}…` : gate.rule_text}</div>
            <details><summary>판정에 쓴 회사 값(엔진 입력)</summary><div className="paw-mono paw-faint">{known(gate.company_value)}</div></details>
          </td></tr>;
        })}</tbody></table>
        {demo && demo.length > 0 && <p className="paw-note">자격 판정에 쓰인 회사 값 가운데 {demo.length}개는 데모 입력이에요.</p>}
      </div>
      <div>
        <h3 className="paw-sub">계약·평가 조건</h3>
        <table className="paw-plain"><tbody>{contractRows(analysis).map(({ name, value, evidence }) =>
          <tr key={name}><th scope="row">{name}</th><td>{value} {name === "공동수급" && consortiumIssue !== undefined
            && <button className="paw-jump" type="button" onClick={() => openIssue(consortiumIssue)}>평가기준 문구와 불일치 →</button>}
            {evidence && <> {pageLink(evidence, name)}</>}</td></tr>)}</tbody></table>
      </div>
    </div>
  </section>;
}

interface SourceProps {
  run: EngineRun | EngineReviewResult;
  analysis: EngineAnalysis;
  shown: PageOverviewView | null;
  notice: NoticeDetailResponse;
  originalFilename?: string;
  portfolio: ReadonlyMap<string, WikiProject>;
  wikiNames: ReadonlyMap<string, string>;
  readProjectCount: number | null;
  locate: (quote: string) => PdfQuoteLocation;
  pagesReady: boolean;
  claimLinks: (claim: PageOverviewFact, label: string) => ReactNode;
  openPdf: ReactNode;
}

export function AnalysisSource({
  run, analysis, shown, notice, originalFilename, portfolio, wikiNames, readProjectCount, locate, pagesReady, claimLinks, openPdf,
}: SourceProps) {
  const project = analysis.facts?.project;
  const requirementCount = analysis.requirement_counts?.source_found;
  const judged = analysis.assessment?.provisional?.fit_coverage.judged;
  const knowledge = analysis.knowledge;
  const workUnits = analysis.work_units;
  const citations = analysis.citations;
  const profitability = analysis.profitability;
  const scoring = analysis.review_actions?.requests.filter(({ purpose }) => purpose === "scoring");
  const claims = shown ? [...shown.payload.business_overview, ...shown.payload.main_tasks, ...shown.payload.budget_and_period] : [];
  const numbered = claims.filter(({ text }) => /\d/.test(text));
  const warnings = shown?.warnings;
  const files = notice.attachments.flatMap(({ acquired_file }) => acquired_file ? [acquired_file] : []);
  const documents = files.filter((file) => /\.(?:hwpx?|pdf)$/i.test(file.filename));
  const file = originalFilename ? files.find(({ filename }) => filename === originalFilename)
    : documents.length === 1 ? documents[0] : null;
  const extension = file?.filename.split(".").at(-1)?.toUpperCase();
  const pageCount = shown?.pdf_page_count;
  const label = qualityStatusLabel(run.quality_status);
  const skippedProjects = knowledge?.skipped.filter((slug) => portfolio.has(slug)) ?? [];
  const skippedPages = knowledge?.skipped.filter((slug) => !portfolio.has(slug)) ?? [];
  const names = (slugs: string[]) => slugs.map((slug) => knowledgeName(slug, portfolio, wikiNames)).join(", ");
  const skipped = [
    skippedProjects.length > 0 && `실적 ${skippedProjects.length}건(${names(skippedProjects)})`,
    names(skippedPages),
  ].filter(Boolean).join("과 ");
  const fitQuotes = analysis.fits.flatMap((fit) => fit.evidence?.quote ? [{ quote: fit.evidence.quote, id: fit.req_id }] : []);
  const gateQuotes = analysis.gates.flatMap((gate) => gate.evidence.filter(({ quote }) => Boolean(quote))
    .map(({ quote }) => ({ quote, id: "참가 자격" })));
  const budgetQuote = project?.evidence.find(({ quote }) => /VAT|부가/.test(quote))?.quote;
  const otherQuotes = [
    budgetQuote, ...(analysis.risks ?? []).map(({ evidence }) => evidence.quote),
    ...contractRows(analysis).map(({ evidence }) => evidence?.quote),
  ].flatMap((quote) => quote ? [{ quote, id: null }] : []);
  const searched = [...fitQuotes, ...gateQuotes, ...otherQuotes].map(({ quote, id }) => ({ kind: locate(quote).kind, id }));
  const exact = searched.filter(({ kind }) => kind === "exact").length;
  const span = searched.filter(({ kind }) => kind === "span").length;
  const missing = searched.filter(({ kind }) => kind === "not_found");
  const missingNames = [...missing.flatMap(({ id }) => id && id !== "참가 자격" ? [id] : [])];
  const missingGates = missing.filter(({ id }) => id === "참가 자격").length;
  if (missingGates > 0) missingNames.push(`참가 자격 ${missingGates}건`);

  return <section className="paw-blk" id="s-source" aria-label="원문·처리 정보">
    <div className="paw-blk-h"><h2>원문·처리 정보</h2><span className="paw-aside">이 분석이 어떤 자료로, 어디까지 만들어졌는지예요</span></div>
    <p className="paw-source-intro">결과를 어디까지 믿고 쓸지 정할 때 보세요. 아래 내용은 모두 이 사업의 실제 처리 기록에서 가져왔어요.</p>
    <dl className="paw-source-meta">
      <dt>분석한 원문</dt><dd>
        <p>{run.documents.length === 1 ? `나라장터 사전규격에 첨부된 제안요청서 1건이에요(${known(file?.filename, "파일명 미확인")}).`
          : run.documents.length > 0 ? `분석 기록에 원문 ${run.documents.length}건이 있어요.` : "분석한 원문은 미확인이에요."}</p>
        <p className="paw-muted">{pageCount && pageCount > 0
          ? extension === "HWPX" || extension === "HWP" ? `원본은 한글(${extension}) 파일이라, 화면의 쪽 번호는 이 파일을 PDF로 바꾼 ${pageCount}쪽 기준이에요.`
            : `화면의 쪽 번호는 제안요청서 PDF ${pageCount}쪽 기준이에요.`
          : "제안요청서 PDF 쪽수는 미확인이에요."} {openPdf}</p>
      </dd>
      <dt>사업 개요의 범위</dt><dd>{shown ? <>
        <p>개요는 PDF {pageCount || "전체 쪽수 미확인"}{pageCount ? "쪽" : ""} 가운데 <b>{shown.reviewed_pages.length ? `${shown.reviewed_pages.join("·")}쪽` : "검토 쪽 미확인"}</b>만 읽고 정리했어요. 다른 쪽 내용은 개요에 들어 있지 않고, 표의 칸 배치도 해석하지 않았어요.</p>
        <p>개요를 원문과 자동으로 대조했을 때 {shown.evidence_check_status === "passed" && shown.validation_status === "passed" ? "실패는 없었고" : "확인이 필요한 결과가 있었고"}, {warnings?.length && warnings.every((code) => Object.hasOwn(overviewWarnings, code)) ? "숫자 관련 " : null}<b>경고 {warnings?.length ?? "미확인"}{warnings ? "건" : ""}</b>{warnings ? "이 있었어요." : "이에요."}</p>
        {warnings && warnings.length > 0 && <ul>{warnings.map((code, i) => <li key={i}>{overviewWarnings[code] ?? "뜻이 등록되지 않은 경고예요."} <span className="paw-code">{code}</span></li>)}</ul>}
        <p className="paw-muted">{warnings && warnings.length > 0 && "어느 문장에서 경고가 나왔는지는 기록에 없어요. "}숫자가 들어 있는 개요 문장은 {numbered.length}개예요. 원문에서 직접 확인해 주세요.</p>
        {numbered.length > 0 && <p>{numbered.map((claim, i) => {
          const name = claim.text.includes("금액") ? "사업 금액" : claim.text.includes("기간") ? "사업 기간"
            : claim.text.startsWith("추진 배경") ? "추진 배경" : `${claim.text.slice(0, 16)}…`;
          return <span className="paw-numbered-claim" key={i}>{name} {claimLinks(claim, `개요 문장: ${name}`)}</span>;
        })}</p>}
      </> : <p>사업 개요의 범위는 미확인이에요.</p>}</dd>
      <dt>심층 분석의 범위</dt><dd>
        <p>{requirementCount != null && judged != null
          ? <>원문에서 요구사항 <b>{requirementCount}건</b>을 찾았고, 그중 <b>{judged}건</b>에 대응 판단을 냈어요.
            {judged <= requirementCount && ` 나머지 ${requirementCount - judged}건은 엔진이 대응을 판단하지 못해 ‘미확인’이에요.`}</>
          : `원문 요구사항 ${requirementCount == null ? "건수 미확인" : `${requirementCount}건`} · 대응 판단 ${judged == null ? "건수 미확인" : `${judged}건`}.`}</p>
        <p>{citations ? `엔진이 근거로 인용한 원문 문장 ${citations.total}개 가운데 ${citations.verified}개는 원문과 글자가 일치하는 것을 확인했고, ${citations.unverified}개는 확인하지 못했어요.`
          : "엔진이 인용한 원문 문장 수는 미확인이에요."}</p>
      </dd>
      <dt>엔진이 본 회사 자료</dt><dd>{workUnits?.status === "classified" ? <p>{workUnitsNotice(workUnits)}</p>
        : knowledge?.skipped.length === 0 ? <p>{knowledgeReadNotice(knowledge.pages.length, readProjectCount)}</p>
        : knowledge ? <>
        <p>회사 근거 위키에서 <b>{knowledge.pages.length}쪽</b>을 읽었어요{knowledge.pages.length > 0 && `: ${names(knowledge.pages)}`}.</p>
        <p>분량 제한 때문에 <b>{knowledge.skipped.length}쪽</b>은 읽지 않았어요{skipped && `: ${skipped}`}.</p>
        <p className="paw-muted">그래서 요구사항이 ‘회사 근거 없음’이어도 회사에 그런 실적이 없다는 뜻은 아니에요. 읽지 않은 실적에 근거가 있을 수 있어요.</p>
      </> : <p>엔진이 본 회사 자료는 미확인이에요.</p>}</dd>
      {workUnits && <>
        <dt>업무 근거 지도</dt><dd><p>{workUnits.status === "classified"
          ? `요구사항 ${workUnits.assignments.length}건을 업무 단위로 분류했어요(지도 실적 ${workUnits.basis_projects}건 기준). 어느 단위에도 들지 않은 요구사항 ${workUnits.assignments.filter(isOutsideWorkUnits).length}건은 ‘수행 기록 없음’으로 판정될 수 있어요.`
          : `분류하지 못했어요${workUnits.reason === null ? "" : `(${workUnits.reason})`}. 이 분석의 ‘부족’은 회사 정보에서 확인된 제약에서만 나와요.`}</p></dd>
      </>}
      <dt>엔진이 요청한 회사 정보</dt><dd>{scoring ? <>
        <p>점수를 추정하려고 회사 정보 <b>{scoring.length}가지</b>를 확인해 달라고 했어요{scoring[0] && `(예: ${scoring[0].title})`}.</p>
        {scoring.length > 0 && <p className="paw-muted">모두 점수 추정용이고 추적 여부를 바꾸는 항목은 없어서, 이 화면에서는 건수만 보여요. 추적 판단에 필요한 확인은 ‘쟁점’에 모아 두었어요.</p>}
      </> : <p>엔진이 요청한 회사 정보는 미확인이에요.</p>}</dd>
      <dt>수익성</dt><dd>{profitability ? <>
        <p>{profitability.est_mm == null ? "엔진은 수익성을 계산하지 못했어요. 엔진이 남긴 이유는 다음과 같아요." : `엔진이 추정한 투입 공수는 ${profitability.est_mm.toLocaleString("ko-KR")}인월이에요.`}</p>
        <blockquote>{known(profitability.note, "값 없음")}</blockquote>
      </> : <p>수익성 검토 결과는 미확인이에요.</p>}</dd>
      <dt>결과를 쓸 때 주의</dt><dd>
        <p>{shown && shown.quality_status === run.quality_status ? <>개요와 심층 분석 모두 <b>{label}</b>이에요.</>
          : <>개요 <b>{shown ? qualityStatusLabel(shown.quality_status) : "미확인"}</b> · 심층 분석 <b>{label}</b>.</>}
          {shown?.quality_status === "unmeasured_reference" && run.quality_status === "unmeasured_reference"
            && " 결과가 얼마나 정확한지 아직 사람이 채점해 본 적이 없다는 뜻이에요."}
          {" "}판단에 쓰기 전에 쪽 단추로 원문을 직접 확인해 주세요.</p>
        <p className="paw-muted">처리 시각: 개요 {analysisDate(shown?.completed_at)} · 심층 분석 {analysisDate(run.completed_at)} ({run.engine_version})</p>
      </dd>
      <dt>쪽 번호를 붙인 방법</dt><dd>
        <p>엔진은 원문 위치를 HWPX 문서의 절 번호로만 줘요. 화면은 엔진이 인용한 문장을 PDF 본문에서 그대로 찾아 쪽 번호를 붙였어요.</p>
        <p className="paw-muted">{pagesReady ? `인용 ${searched.length}문장 가운데 ${exact}개는 한 쪽에서 찾았고${span > 0 ? `, ${span}개는 이웃한 두 쪽에서 찾았고` : ""}, ${missing.length}개${missingNames.length > 0 ? `(${missingNames.join(", ")})` : ""}는 찾지 못해 ‘쪽 없음’으로 보여요.`
          : "PDF 본문에서 찾은 인용 문장 수는 미확인이에요."}</p>
      </dd>
    </dl>
  </section>;
}

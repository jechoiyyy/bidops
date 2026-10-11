import { useQuery } from "@tanstack/react-query";
import { Badge, type BadgeVariant } from "../common/Badge";
import { EmptyState } from "../common/EmptyState";
import { describeCompanyApiError } from "../../lib/apiErrors";
import {
  companyApi,
  companyFactStatusLabel,
  companyFitDecisionLabel,
  companyFitReasonKindLabel,
  companyFitStatusLabel,
  companyKeys,
  graphPathRelationLabel,
  shortIdentity,
  type CompanyFitReasonV2,
  type CompanyScopedFitView,
  type Uuid,
} from "../../lib/companyApi";
import { formatDateTime, present } from "../../lib/format";
import { qualityStatusLabel, qualityStatusNote } from "../../lib/qualityStatus";
import "../../styles/company-workspace.css";

/*
 * 회사 핏 판정 이력 (`GET /api/companies/{id}/pre-specs/{notice_id}/company-fit`, 공통 계약 §6).
 *
 * - 서버가 준 순서(created_at DESC, id DESC)를 그대로 쓴다. 맨 위가 가장 최근 실행이다.
 * - 판정(부합·불일치·미확인)은 `completed`이고 검증된 결과가 있을 때만 적는다. 대기·실행 중·
 *   실패·사람 검토 필요는 판정이 아니며 "판정 없음"과 실행 상태를 따로 적는다.
 * - 사유의 그래프 경로는 서버가 준 `paths[graph_path_indexes[i]]`를 그대로 그린다. 경로를
 *   만들거나 이어 붙이지 않고, index가 범위 밖이면 그 사실을 적는다.
 * - 회사 핏은 CLI로만 실행한다. 이 화면에는 생성·승인 동작이 없다.
 */

function statusVariant(attempt: CompanyScopedFitView): BadgeVariant {
  if (attempt.status === "failed") return "danger";
  if (attempt.status === "needs_human_review") return "alert";
  return "neutral";
}

/** completed이고 검증된 결과가 있을 때만 판정을 돌려준다. 그 밖은 null(판정 없음). */
function attemptDecision(attempt: CompanyScopedFitView) {
  return attempt.status === "completed" && attempt.result !== null ? attempt.result.decision : null;
}

function GraphPathView({ index, attempt }: { index: number; attempt: CompanyScopedFitView }) {
  const path = Number.isInteger(index) && index >= 0 ? attempt.paths[index] : undefined;
  if (path === undefined) {
    return (
      <li className="cw-path cw-path-missing" data-path-index={index}>
        서버가 가리킨 경로 {index}번이 이 실행의 경로 목록 범위 밖입니다. 경로를 만들어 채우지 않았습니다.
      </li>
    );
  }
  return (
    <li className="cw-path" data-path-index={index} data-path-relation={path.relation}>
      <span className="cw-path-head">
        <Badge variant="neutral" label={`경로 ${index} · ${graphPathRelationLabel(path.relation)}`} />
        <span className="cw-caption">요구사항 {path.requirement_id}</span>
      </span>
      {path.node_ids.length > 0 ? (
        <span className="cw-path-line" data-path-nodes>
          <span className="cw-caption">노드</span> {path.node_ids.map((nodeId, position) => (
            <span key={`${nodeId}:${position}`}>
              {position > 0 ? " → " : ""}
              <code>{nodeId}</code>
            </span>
          ))}
        </span>
      ) : (
        <span className="cw-caption">서버가 연결된 노드를 주지 않았습니다.</span>
      )}
      {path.edge_ids.length > 0 ? (
        <span className="cw-path-line" data-path-edges>
          <span className="cw-caption">관계</span> {path.edge_ids.map((edgeId, position) => (
            <span key={`${edgeId}:${position}`}>
              {position > 0 ? ", " : ""}
              <code>{edgeId}</code>
            </span>
          ))}
        </span>
      ) : null}
      <span className="cw-caption">프로필 근거 {path.profile_evidence_ids.length}건</span>
    </li>
  );
}

function ReasonView({ reason, attempt }: { reason: CompanyFitReasonV2; attempt: CompanyScopedFitView }) {
  return (
    <li className="cw-reason" data-reason-kind={reason.kind}>
      <span className="cw-reason-head">
        <Badge variant="neutral" label={companyFitReasonKindLabel(reason.kind)} />
      </span>
      <span className="cw-summary-text">{reason.explanation}</span>
      {reason.notice_refs.length > 0 ? (
        <ul className="cw-ref-list" aria-label="공고 근거">
          {reason.notice_refs.map((ref) => {
            const fact = attempt.notice_facts.find((entry) => entry.ref === ref);
            return (
              <li className="cw-caption" key={ref}>
                공고 근거 <code>{ref}</code>
                {fact ? ` · ${fact.text}${fact.pages.length > 0 ? ` (p.${fact.pages.join(", ")})` : ""}` : ""}
              </li>
            );
          })}
        </ul>
      ) : null}
      {reason.company_refs.length > 0 ? (
        <ul className="cw-ref-list" aria-label="회사 근거">
          {reason.company_refs.map((ref) => {
            const fact = attempt.company_facts.find((entry) => entry.ref === ref);
            return (
              <li className="cw-caption" key={ref}>
                회사 사실 <code>{fact ? fact.fact_key : ref}</code>
                {fact ? ` · ${companyFactStatusLabel(fact.status)}` : ""}
              </li>
            );
          })}
        </ul>
      ) : null}
      {reason.graph_path_indexes.length > 0 ? (
        <ul className="cw-path-list" aria-label="이 사유의 그래프 경로">
          {reason.graph_path_indexes.map((index, position) => (
            <GraphPathView attempt={attempt} index={index} key={`${index}:${position}`} />
          ))}
        </ul>
      ) : (
        <span className="cw-caption" data-no-graph-path>연결된 그래프 경로 없음</span>
      )}
    </li>
  );
}

function AttemptView({ attempt, latest }: { attempt: CompanyScopedFitView; latest: boolean }) {
  const decision = attemptDecision(attempt);
  const result = attempt.status === "completed" ? attempt.result : null;
  return (
    <li
      className="cw-attempt"
      data-attempt-id={attempt.id}
      data-attempt-status={attempt.status}
      data-attempt-decision={decision ?? "null"}
      data-attempt-current={attempt.is_current ? "true" : "false"}
    >
      <span className="cw-attempt-head">
        <Badge variant={statusVariant(attempt)} label={`실행 ${companyFitStatusLabel(attempt.status)}`} />
        <Badge variant="neutral" label={decision === null ? companyFitDecisionLabel(null) : `판정 ${companyFitDecisionLabel(decision)}`} />
        {latest ? <Badge variant="info" label="최신 실행" /> : null}
        {attempt.is_current
          ? <Badge variant="neutral" label="현재 입력 기준" />
          : <Badge variant="alert" label="현재 입력 기준 아님(이전 입력)" />}
        <span className="cw-caption">{formatDateTime(attempt.created_at)}</span>
      </span>
      {attempt.status === "failed" ? (
        <p className="cw-caption" data-attempt-error>실행 실패 · 오류 코드 {present(attempt.error_code, "없음")}. 실패는 판정이 아니며 결과로 읽지 않습니다.</p>
      ) : null}
      {attempt.status === "needs_human_review" ? (
        <p className="cw-caption">모델 결과를 자동으로 확정하지 못해 사람 검토가 필요합니다. 판정으로 읽지 않습니다.</p>
      ) : null}
      {attempt.status === "queued" || attempt.status === "running" ? (
        <p className="cw-caption">아직 끝나지 않은 실행입니다. 판정이 아닙니다.</p>
      ) : null}
      {result ? (
        <>
          <p className="cw-summary-text" data-attempt-summary>{result.summary}</p>
          {result.reasons.length > 0 ? (
            <ol className="cw-reason-list" aria-label="판정 사유">
              {result.reasons.map((reason, position) => (
                <ReasonView attempt={attempt} key={position} reason={reason} />
              ))}
            </ol>
          ) : (
            <p className="cw-caption">서버가 판정 사유를 주지 않았습니다.</p>
          )}
          {result.verification_items.length > 0 ? (
            <div>
              <p className="cw-caption">확인이 필요한 항목</p>
              <ul className="cw-ref-list" aria-label="확인이 필요한 항목">
                {result.verification_items.map((item, position) => <li key={position}>{item}</li>)}
              </ul>
            </div>
          ) : null}
        </>
      ) : null}
      <dl className="cw-facts cw-attempt-meta">
        <dt>그래프 버전</dt><dd><code title={attempt.graph_version_id}>{shortIdentity(attempt.graph_version_id, 8)}</code> · 온톨로지 {attempt.ontology_version}</dd>
        <dt>입력 해시</dt><dd><code title={attempt.input_sha256} data-input-sha>{shortIdentity(attempt.input_sha256, 12)}</code></dd>
        <dt>모델</dt><dd>{attempt.model_name} · revision {present(attempt.model_revision, "선언 없음")}</dd>
        <dt>품질 표식</dt>
        <dd data-quality-status={attempt.quality_status ?? "null"}>
          {qualityStatusLabel(attempt.quality_status)} · <span className="cw-caption">{qualityStatusNote(attempt.quality_status)}</span>
        </dd>
      </dl>
    </li>
  );
}

export function CompanyFitAttempts({ companyId, noticeId }: { companyId: Uuid; noticeId: number }) {
  const attemptsQuery = useQuery({
    queryKey: companyKeys.companyFit(companyId, noticeId),
    queryFn: ({ signal }) => companyApi.getCompanyFit(companyId, noticeId, { signal }),
    retry: false,
  });
  const view = attemptsQuery.data;
  const scopeMismatch = view !== undefined && (view.company_id !== companyId || view.notice_id !== noticeId);
  return (
    <section className="cw-section" aria-labelledby="company-fit-title" data-testid="company-fit">
      <h3 id="company-fit-title">회사 핏 판정 이력</h3>
      <p className="cw-caption" data-testid="company-fit-cli-note">
        회사 핏은 CLI로만 실행합니다. 이 화면에서는 핏을 만들거나 승인하지 않고 결과·사유·경로만 봅니다.
      </p>
      {attemptsQuery.isPending ? (
        <p role="status">핏 판정 이력을 불러오는 중입니다.</p>
      ) : attemptsQuery.isError ? (
        <EmptyState
          compact
          tone="error"
          title="핏 판정 이력을 불러오지 못했습니다."
          problem={describeCompanyApiError(attemptsQuery.error, "핏 판정 이력을 불러오지 못했습니다.")}
          action={{ label: "다시 시도", onClick: () => { void attemptsQuery.refetch(); } }}
        />
      ) : scopeMismatch ? (
        <EmptyState
          compact
          tone="error"
          title="응답의 회사·공고가 이 화면과 다릅니다."
          description="다른 회사의 결과를 대신 보여 주지 않습니다."
        />
      ) : view && view.attempts.length === 0 ? (
        <p data-testid="company-fit-empty">이 회사의 핏 실행 기록이 없습니다. 기록 없음은 불일치가 아닙니다.</p>
      ) : view ? (
        <ol className="cw-attempt-list" aria-label="회사 핏 판정 이력(최신순)">
          {view.attempts.map((attempt, position) => (
            <AttemptView attempt={attempt} key={attempt.id} latest={position === 0} />
          ))}
        </ol>
      ) : null}
    </section>
  );
}

import { useMemo, useState } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { Button } from "@astryxdesign/core/Button";
import { EmptyState } from "../components/common/EmptyState";
import { PageViewDialog } from "../components/verdict/PageViewDialog";
import { RequirementTable } from "../components/verdict/RequirementTable";
import { SourcePanel } from "../components/verdict/SourcePanel";
import { describeVerdictApiError, describeVerdictRunCode } from "../lib/apiErrors";
import type { PractitionerVerdictView, VerdictFeedbackKind, VerdictMatrixRow } from "../lib/types";
import {
  isVerdictActive,
  resolveStructureId,
  sectionLabel,
  staleReasonLabel,
} from "../lib/verdict";
import "../styles/verdict.css";

/*
 * 사업기회 레코드의 판정 탭 본문(`/opportunities/:id/verdict`, RL-03 spec "화면", ui-spec §4.4).
 *
 * 상태 6종은 서버 `availability`를 그대로 읽는다 — 화면이 판정이나 진행 상태를 다시 계산하지 않는다.
 *   none                  "아직 판정이 없습니다" + 다시 판정
 *                         (권위 연결 사전규격이 없으면 `notice_id=null` — 판정 대상이 없으므로 요청 버튼 없이 안내만)
 *   pending · running     "분석 중" + 검증이 끝난 부분표
 *   failed · needs_human_review  "사람 검토가 필요합니다" + 부분표 + 다시 판정(자동 보정·재시도 없음)
 *   legacy                기존 보고서 링크
 *   completed             좌측 요약(레코드 페이지가 그림) + 요구사항 표 + 원문 패널
 *   is_current=false      "과거 기준" pill + 한글 stale 사유(어느 상태에서도)
 * 좌측 요약(판정 이름·체크리스트·다음 행동)은 레코드 페이지의 좌측 열이라 이 파일이 그리지 않는다.
 * 정책 id·모델명·hash·품질 표식은 이 파일 어디에도 그리지 않는다(⋯ "실행 정보"에서만).
 */

interface OpportunityVerdictTabProps {
  query: UseQueryResult<PractitionerVerdictView>;
  /** "다시 판정" 요청 대화상자를 연다. */
  onRequest: () => void;
  /** 판정 오류 제보 대화상자를 연다(요구사항 한 행에서 열면 그 행과 유형을 준다). */
  onFeedback: (target: { row: VerdictMatrixRow; kind: VerdictFeedbackKind }) => void;
}

export function OpportunityVerdictTab({ query, onRequest, onFeedback }: OpportunityVerdictTabProps) {
  const [selectedUnitId, setSelectedUnitId] = useState<string | null>(null);
  const [pageDialog, setPageDialog] = useState<{ structureId: string; page: number; blocks: string[] } | null>(null);

  const view = query.data ?? null;
  const rows = useMemo<readonly VerdictMatrixRow[]>(() => {
    if (!view) return [];
    return view.availability === "completed" && view.result ? view.result.matrix : view.partial_matrix;
  }, [view]);

  if (query.isPending) {
    return <p className="rec-status" role="status">판정을 불러오는 중입니다.</p>;
  }
  if (query.isError || !view) {
    return (
      <EmptyState
        action={{ label: "다시 시도", onClick: () => { void query.refetch(); } }}
        compact
        problem={describeVerdictApiError(query.error, "판정을 불러오지 못했습니다.")}
        title="판정을 불러오지 못했습니다"
        tone="error"
      />
    );
  }

  const active = isVerdictActive(view);
  const stale = !view.is_current && view.availability !== "none";
  const selected = rows.find((row) => row.unit_id === selectedUnitId) ?? null;

  const staleBanner = stale ? (
    <div className="vd-banner" data-testid="stale-banner" role="status">
      <span className="vd-pill is-muted">과거 기준</span>
      <p>
        {view.stale_reasons.length > 0
          ? `${view.stale_reasons.map(staleReasonLabel).join(" · ")}. 이 판정은 지금 기준이 아닙니다.`
          : "이 판정은 지금 기준이 아닙니다."}
      </p>
    </div>
  ) : null;

  if (view.notice_id === null) {
    // 서버는 사전규격이 없는 사업기회에 200 none(`notice_id=null`)을 준다. 1차 판정은 사전규격만
    // 대상이고 요청해도 404이므로 "다시 판정"을 두지 않는다(0으로 접어 요청하지 않는다).
    return (
      <EmptyState
        compact
        description="이 사업기회에는 연결된 사전규격이 없어 판정 대상이 아닙니다. 판정은 사전규격 제안요청서를 기준으로 합니다."
        title="아직 판정이 없습니다"
      />
    );
  }

  if (view.availability === "none") {
    return (
      <EmptyState
        action={{ label: "다시 판정", onClick: onRequest }}
        compact
        description="판정은 SW사업 사전규격의 문서 준비가 끝나고 분석이 승인되어 있을 때 시작됩니다. 지금 바로 분석을 요청할 수도 있습니다."
        title="아직 판정이 없습니다"
      />
    );
  }

  if (view.availability === "legacy") {
    return (
      <>
        {staleBanner}
        <EmptyState
          action={{ label: "기존 보고서 보기", to: `/pre-specs/${view.notice_id}` }}
          compact
          description="이전 방식의 심층 검토 보고서만 있고 요구사항 단위 판정은 없습니다."
          secondaryAction={{ label: "다시 판정", onClick: onRequest }}
          title="기존 보고서가 있습니다"
        />
      </>
    );
  }

  const humanReview = view.availability === "failed" || view.availability === "needs_human_review";
  const runCode = describeVerdictRunCode(view.error_code);
  const incomplete = view.availability !== "completed";

  if (view.availability === "completed" && !view.result) {
    return (
      <EmptyState
        action={{ label: "다시 시도", onClick: () => { void query.refetch(); } }}
        compact
        description="서버가 완료로 알렸지만 판정 결과가 비어 있습니다. 완료로 보여 주지 않습니다."
        title="판정 결과를 읽을 수 없습니다"
        tone="error"
      />
    );
  }

  return (
    <div className={`vd-layout${selected ? " has-source" : ""}`}>
      <div className="vd-center">
        {staleBanner}
        {active ? (
          <div className="vd-banner" data-testid="running-banner" role="status">
            <strong>분석 중</strong>
            <p>검증이 끝난 요구사항부터 아래 표에 나타납니다. 분석이 끝나면 판정이 보입니다.</p>
          </div>
        ) : null}
        {view.availability === "completed" && view.missing_sections.length > 0 ? (
          // 결정 B23: 원문에서 찾지 못한 영역이 있어도 판정은 완료되며, 그 영역의 요구사항은
          // 확인 필요로 남는다(서버가 이때 "진행 가능"을 내지 않는다). 화면은 영역 목록만 그대로 보인다.
          <div className="vd-banner" data-testid="missing-sections-note" role="note">
            <p>
              원문에서 찾지 못한 영역: {view.missing_sections.map(sectionLabel).join(", ")} — 이 영역의 요구사항은 확인 필요입니다.
            </p>
          </div>
        ) : null}
        {humanReview ? (
          <div className="vd-banner is-warning" data-testid="review-banner" role="status">
            <div className="vd-banner-body">
              <strong>사람 검토가 필요합니다</strong>
              {runCode ? (
                <p>
                  {runCode.title}
                  {runCode.detail ? ` ${runCode.detail}` : ""}
                  {runCode.code ? <span className="vd-code"> 오류 코드 {runCode.code}</span> : null}
                </p>
              ) : null}
              {view.missing_sections.length > 0 ? (
                <p>
                  찾지 못한 영역: {view.missing_sections.map(sectionLabel).join(", ")}. 원문에 없다는 뜻은 아닙니다.
                </p>
              ) : null}
              {runCode?.detail ? null : (
                <p>검증을 통과하지 못한 결과는 자동으로 고치지 않습니다. 아래 표는 검증이 끝난 부분만 보여 줍니다.</p>
              )}
            </div>
            <Button label="다시 판정" onClick={onRequest} size="sm" />
          </div>
        ) : null}
        <RequirementTable
          note={incomplete ? "검증이 끝난 요구사항만 보입니다. 최종 판정은 아직 없습니다." : null}
          onSelect={setSelectedUnitId}
          rows={rows}
          selectedUnitId={selected?.unit_id ?? null}
        />
      </div>

      {selected ? (
        <SourcePanel
          feedbackDisabledReason={view.attempt_id === null ? "제보할 판정 실행이 없습니다" : null}
          onClose={() => setSelectedUnitId(null)}
          onFeedback={(kind) => onFeedback({ row: selected, kind })}
          onViewPage={() => {
            const structureId = resolveStructureId(view, selected);
            if (structureId === null || selected.page_range === null) return;
            setPageDialog({
              structureId,
              page: selected.page_range.first,
              blocks: selected.evidence_refs.slice(0, 2).map((ref) => ref.block_key),
            });
          }}
          row={selected}
          structureId={resolveStructureId(view, selected)}
        />
      ) : null}

      {pageDialog ? (
        <PageViewDialog
          highlightBlockKeys={pageDialog.blocks}
          onClose={() => setPageDialog(null)}
          open
          page={pageDialog.page}
          structureId={pageDialog.structureId}
        />
      ) : null}
    </div>
  );
}

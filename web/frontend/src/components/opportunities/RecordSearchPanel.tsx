import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@astryxdesign/core/Button";
import { ActorField } from "../common/ActorField";
import { DisabledReason } from "../common/DisabledReason";
import { MutationFeedback } from "../common/MutationFeedback";
import { ApiError, api } from "../../lib/api";
import { describeApiError, type ApiErrorDescription } from "../../lib/apiErrors";
import type { OpportunityLinkView, OpportunitySearchResponse, OpportunitySearchTarget } from "../../lib/types";
import {
  agencyMatchLabel,
  formatMoment,
  searchStrategyLabel,
  searchTargetLabel,
} from "./trackingFlow";

/**
 * 단계 줄의 `사전규격 찾아보기`·`입찰공고 찾아보기` (spec §4.3, §11.1).
 *
 * 서버가 수집 색인에서 이름 사다리로 찾아 **후보만** 만든다. 연결을 확정하지 않으며
 * 수용·기각은 후보 대화상자에서 사람이 한다. 찾지 못하면 `검색 미확인`이고 그것은
 * 레코드가 없다는 뜻이 아니다. 찾아보기는 감사 기록을 남기는 요청이라 결정 기록자를
 * 받고 사람이 실행 단추를 눌러야 나간다.
 */

const SOURCE_MISSING_TEXT: Record<OpportunitySearchTarget, string> = {
  pre_spec: "이 사업기회가 소유한 발주계획이 없어 사전규격을 찾아볼 기준이 없습니다. 발주계획이 확정 연결된 뒤에 찾아볼 수 있습니다.",
  bid_notice: "이 사업기회가 소유한 사전규격이나 발주계획이 없어 입찰공고를 찾아볼 기준이 없습니다. 둘 중 하나가 확정 연결된 뒤에 찾아볼 수 있습니다.",
};

function sourceMissingTarget(error: unknown, fallback: OpportunitySearchTarget): OpportunitySearchTarget | null {
  if (!(error instanceof ApiError) || error.code !== "search_source_missing") return null;
  const detail = error.detail;
  const details = typeof detail === "object" && detail !== null && "details" in detail ? detail.details : null;
  const target = typeof details === "object" && details !== null && "target" in details ? details.target : null;
  return target === "pre_spec" || target === "bid_notice" ? target : fallback;
}

export interface RecordSearchPanelProps {
  opportunityId: number;
  target: OpportunitySearchTarget;
  onClose: () => void;
  /** 결과 후보 하나를 후보 연결 확인 대화상자로 연다. */
  onOpenCandidate: (candidate: OpportunityLinkView) => void;
  /** 가장 최근 결과. 상세가 들고 있어 대상을 바꿔도 결과를 잃지 않는다. */
  result: OpportunitySearchResponse | null;
  onResult: (result: OpportunitySearchResponse) => void;
}

export function RecordSearchPanel({
  onClose,
  onOpenCandidate,
  onResult,
  opportunityId,
  result,
  target,
}: RecordSearchPanelProps) {
  const queryClient = useQueryClient();
  const [actorName, setActorName] = useState("");
  const [problem, setProblem] = useState<ApiErrorDescription | null>(null);
  const [missing, setMissing] = useState<OpportunitySearchTarget | null>(null);
  const label = searchTargetLabel(target);

  const mutation = useMutation({
    mutationFn: () => api.searchOpportunityRecords(opportunityId, { target }, actorName),
    onSuccess: async (response) => {
      setProblem(null);
      setMissing(null);
      onResult(response);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["opportunity", opportunityId] }),
        queryClient.invalidateQueries({ queryKey: ["opportunities"] }),
      ]);
    },
    onError: async (caught: unknown) => {
      const source = sourceMissingTarget(caught, target);
      if (source !== null) {
        setProblem(null);
        setMissing(source);
        // 화면이 가진 연결이 서버와 달랐다는 뜻이므로 최신 연결을 다시 읽는다.
        await queryClient.invalidateQueries({ queryKey: ["opportunity", opportunityId] });
        return;
      }
      setMissing(null);
      setProblem(describeApiError(caught, `${label} 찾아보기를 실행하지 못했습니다.`));
    },
  });

  const disabledReason = mutation.isPending
    ? `${label} 찾아보기를 실행하고 있습니다.`
    : !actorName.trim()
      ? "찾아보기를 실행하려면 결정 기록자를 입력하십시오."
      : null;
  const shown = result && result.target === target ? result : null;

  return (
    <section aria-label={`${label} 찾아보기`} className="opportunity-record-search">
      <div className="opportunity-row opportunity-spread">
        <h4>{label} 찾아보기</h4>
        <Button label="찾아보기 닫기" onClick={onClose} size="sm" variant="ghost" />
      </div>
      <p className="opportunity-caption">
        수집 색인에서 이름으로 찾아 후보만 만듭니다. 연결을 확정하지 않으며 수용·기각은 사람이 합니다.
      </p>
      <div className="opportunity-record-search-form">
        <ActorField
          autoComplete="off"
          label="결정 기록자"
          onChange={setActorName}
          placeholder="이름 입력"
          required
          value={actorName}
        />
        <Button
          aria-describedby={disabledReason ? `opportunity-search-disabled-${target}` : undefined}
          isDisabled={disabledReason !== null}
          label={mutation.isPending ? "찾는 중…" : "찾아보기 실행"}
          onClick={() => {
            if (disabledReason === null) mutation.mutate();
          }}
          size="sm"
          variant="primary"
        />
      </div>
      {disabledReason ? (
        <DisabledReason id={`opportunity-search-disabled-${target}`}>{disabledReason}</DisabledReason>
      ) : null}

      {missing ? (
        <MutationFeedback tone="warning">
          <p>{SOURCE_MISSING_TEXT[missing]}</p>
          <p className="opportunity-caption">최신 연결 현황을 다시 읽었습니다.</p>
        </MutationFeedback>
      ) : null}
      {problem ? <MutationFeedback problem={problem} tone="error" /> : null}

      {shown ? (
        <div className="opportunity-search-result" aria-live="polite">
          <p className="opportunity-caption">
            시도한 방식 · {shown.attempted_strategies.length > 0
              ? shown.attempted_strategies.map(searchStrategyLabel).join(", ")
              : "미확인"}
          </p>
          {shown.candidates.length > 0 ? (
            <p className="opportunity-caption">
              후보 {shown.candidates.length}건 · 마지막 검색 {formatMoment(shown.searched_at)}
            </p>
          ) : null}
          {shown.candidates.length > 0 ? (
            <ul aria-label={`${label} 후보`} className="opportunity-search-results">
              {shown.candidates.map((candidate) => (
                <li className="opportunity-search-candidate" key={candidate.id}>
                  <div>
                    <p><strong>{candidate.title?.trim() || "제목 미확인"}</strong></p>
                    <p>{candidate.agency?.trim() || "기관 미확인"}</p>
                    <p className="opportunity-caption">
                      {searchStrategyLabel(candidate.search_strategy)} · {agencyMatchLabel(candidate.agency_match)}
                    </p>
                  </div>
                  <Button label="후보 확인" onClick={() => onOpenCandidate(candidate)} size="sm" />
                </li>
              ))}
            </ul>
          ) : shown.search_unconfirmed ? (
            <div className="opportunity-search-log">
              <p><strong>검색 미확인 · 마지막 검색 {formatMoment(shown.searched_at)}</strong></p>
              <p>이름으로 찾지 못했습니다. 레코드가 없다는 뜻이 아닙니다.</p>
            </div>
          ) : (
            <p className="opportunity-caption">
              새로 만든 후보가 없고 검색 미확인도 아닙니다. 찾은 레코드가 이미 이 사업에 연결됐을 수 있어 연결 현황을
              다시 읽었습니다.
            </p>
          )}
        </div>
      ) : null}
    </section>
  );
}

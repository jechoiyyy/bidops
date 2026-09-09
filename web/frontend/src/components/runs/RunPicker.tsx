import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { api } from "../../lib/api";
import { formatRunRange } from "../../lib/format";
import type { RunSummary } from "../../lib/types";
import { Caption } from "./RunStatusPrimitives";

/**
 * 회차 선택기.
 *
 * 첨부 확보와 산출물 감사는 회차 하나를 골라야 하는 화면이다. 상단 전역 회차
 * 선택기는 이 화면에서 보이지 않으므로(ADR-0046 결정 7) 여기서 직접 고른다.
 * 고른 회차는 주소의 `run` 파라미터에 남겨 링크와 다른 탭이 그대로 읽는다.
 *
 * 시안은 한 회차 예시만 보여 주지만 실제 화면은 조회 중·조회 실패·회차 없음을
 * 각각 구분해야 한다.
 */
export function useSelectedRun(): {
  runs: RunSummary[];
  selectedRunId: string | null;
  selectRun: (runId: string) => void;
  isPending: boolean;
  isError: boolean;
  refetch: () => void;
} {
  const [searchParams, setSearchParams] = useSearchParams();
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: api.getRuns, staleTime: 30_000 });
  const runs = runsQuery.data?.items ?? [];
  const queryRunId = searchParams.get("run");
  const selectedRunId = runs.some((run) => run.run_id === queryRunId) ? queryRunId : runs[0]?.run_id ?? null;

  const selectRun = (runId: string) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("run", runId);
      return next;
    }, { replace: true });
  };

  // 고른 회차가 주소에 없으면 채워 둔다. 무관한 쿼리는 지우지 않는다.
  useEffect(() => {
    if (!selectedRunId || selectedRunId === queryRunId) return;
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("run", selectedRunId);
      return next;
    }, { replace: true });
  }, [queryRunId, selectedRunId, setSearchParams]);

  return {
    runs,
    selectedRunId,
    selectRun,
    isPending: runsQuery.isPending,
    isError: Boolean(runsQuery.error),
    refetch: () => { void runsQuery.refetch(); },
  };
}

export function RunPickerField({
  label,
  runs,
  selectedRunId,
  onSelect,
  isPending,
  isError,
  onRetry,
}: {
  label: string;
  runs: RunSummary[];
  selectedRunId: string | null;
  onSelect: (runId: string) => void;
  isPending: boolean;
  isError: boolean;
  onRetry: () => void;
}) {
  return (
    <div className="rs-field">
      <Selector
        label={label}
        size="sm"
        options={runs.map((run) => ({
          value: run.run_id,
          label: `${formatRunRange(run.run_id, run.window_from, run.window_to)} · ${run.run_id}`,
        }))}
        value={selectedRunId ?? undefined}
        onChange={onSelect}
        placeholder={isPending ? "회차를 불러오는 중…" : isError ? "회차를 확인할 수 없음" : "회차 선택"}
        emptyText="표시할 회차가 없습니다."
        hasSearch
      />
      {isError ? (
        <div className="rs-inline-error" role="alert">
          <Text as="span">회차 목록을 불러오지 못했습니다.</Text>
          <Button label="다시 시도" size="sm" onClick={onRetry} />
        </div>
      ) : null}
      {!isError && !isPending && runs.length === 0 ? (
        <Caption>적재된 회차가 없습니다. 없음을 정상으로 해석하지 않습니다.</Caption>
      ) : null}
    </div>
  );
}

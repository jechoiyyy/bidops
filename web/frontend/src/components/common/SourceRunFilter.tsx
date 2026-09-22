import type { ReactNode } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { buildSourceRunOptions } from "../../lib/runOptions";
import type { RunSummary } from "../../lib/types";

/**
 * 수집 회차 선택 — 발주계획·사전규격이 공유하는 하나의 선택기(명세 §2.1, 시안 M1 승인).
 *
 * **표시만 맡는다.** 고른 회차를 URL에 어떻게 쓰는지(다른 조건을 지우는가 더하는가,
 * 어떤 확인을 먼저 받는가)는 화면이 소유한다 — 두 화면의 URL 계약이 서로 다른 축을
 * 갖기 때문이다. 이 컴포넌트는 옵션 문구·검색·로딩·오류 표현만 같게 만든다.
 *
 * 기반으로 쓰지 않는 것:
 * - `ReviewFilterSelector`: 라벨 숨김이 고정이고 검색·오류 개념이 없다.
 * - `runs/RunPicker`: 회차가 필수라 첫 회차를 자동으로 고르고 `?run=`을 강제한다.
 *   여기서는 누적이 기본이며 **회차를 고르지 않은 상태가 정상**이다.
 */

function joinClassNames(...names: Array<string | undefined | false>): string {
  return names.filter(Boolean).join(" ");
}

/** 누적(회차 미선택)을 뜻하는 옵션 값. URL에는 `source_run_id` 자체가 실리지 않는다. */
export const ALL_SOURCE_RUNS_VALUE = "";
export const ALL_SOURCE_RUNS_LABEL = "모든 수집 회차";

export interface SourceRunFilterProps {
  /** 이 화면이 읽는 수집 회차. 화면이 자기 `kind`로 걸러 넘긴다. */
  runs: readonly RunSummary[];
  /** 회차 목록에 없지만 화면이 아는 회차(발주계획의 실행이 가리키는 회차). */
  extraRunIds?: readonly string[];
  /** 지금 걸린 회차. `null`이면 누적이다. */
  value: string | null;
  /** 누적을 고르면 `null`이 간다. */
  onChange: (runId: string | null) => void;
  isPending: boolean;
  isError: boolean;
  onRetry: () => void;
  isDisabled?: boolean;
  /** 누적 옵션의 설명. 화면마다 누적의 뜻이 달라 문구를 화면이 준다. */
  allRunsDescription: string;
  className?: string;
}

export function SourceRunFilter({
  runs,
  extraRunIds,
  value,
  onChange,
  isPending,
  isError,
  onRetry,
  isDisabled = false,
  allRunsDescription,
  className,
}: SourceRunFilterProps) {
  const options = [
    { value: ALL_SOURCE_RUNS_VALUE, label: ALL_SOURCE_RUNS_LABEL, description: allRunsDescription },
    ...buildSourceRunOptions({
      runs,
      extraRunIds,
      selectedRunId: value,
      isError,
      audience: "practitioner",
    }),
  ];

  return (
    <div className={joinClassNames("source-run-filter", className)} data-review-primitive="source-run-filter">
      <Selector
        className="source-run-filter-selector"
        emptySearchText="일치하는 수집 회차가 없습니다"
        emptyText="조회된 수집 회차가 없습니다"
        hasSearch
        isDisabled={isDisabled}
        isLoading={isPending}
        label="수집 회차"
        onChange={(next) => onChange(next || null)}
        options={options}
        placeholder={isPending ? "회차 목록 조회 중" : ALL_SOURCE_RUNS_LABEL}
        searchPlaceholder="회차 검색"
        size="sm"
        value={value ?? ALL_SOURCE_RUNS_VALUE}
      />
      {/* 회차를 고르지 않은 사람에게 회차 목록 조회 실패는 업무 장애가 아니다. 화면
          맨 위 배너가 아니라 이 컨트롤 안에서만 알리고 목록 자체는 막지 않는다. */}
      {isError ? (
        <div className="source-run-filter-error" role="alert">
          <Text type="supporting" color="secondary" as="span">수집 회차 목록을 불러오지 못했습니다.</Text>
          <Button label="다시 시도" onClick={onRetry} size="sm" variant="ghost" />
        </div>
      ) : null}
    </div>
  );
}

export interface SourceRunContextLineProps {
  /** 지금 걸린 회차의 이름. 옵션 목록에서 그대로 가져온다. */
  label: string;
  /** 회차 이름을 확인할 수 없는 이유(회차 목록 조회 실패 등). */
  reason?: string | null;
  /** `측정 전용 실행` 같은 경고 표식. 화면이 조건을 판정해 넘긴다. */
  badge?: ReactNode;
  onClearRun: () => void;
  className?: string;
}

/**
 * 필터 둘째 줄의 회차 줄 — **상세 필터를 접었는지와 무관하게** 그린다.
 *
 * 접는 것은 보이는 정도이지 걸린 필터를 없애는 일이 아니다. 회차가 걸린 목록은 누적이
 * 아니므로, 그 사실과 되돌리는 길(`모든 회차로`)이 늘 한자리에 있어야 한다. 측정·참조
 * 실행 표식도 이 줄이 진다(M1 승인 A안) — 운영 판정이 아닌 목록을 운영 판정으로 읽지
 * 않게 하는 것은 저장소의 강제 게이트다.
 */
export function SourceRunContextLine({
  label,
  reason,
  badge,
  onClearRun,
  className,
}: SourceRunContextLineProps) {
  return (
    <div className={joinClassNames("source-run-context", className)} data-review-primitive="source-run-context">
      <Text type="label" color="primary" as="span">회차 보기</Text>
      <Text type="supporting" color="secondary" as="span" className="source-run-context-label">· {label}</Text>
      {badge}
      {reason ? (
        <Text type="supporting" color="secondary" as="span" role="alert" className="source-run-context-reason">
          · {reason}
        </Text>
      ) : null}
      <Button label="모든 회차로" onClick={onClearRun} size="sm" variant="ghost" />
    </div>
  );
}

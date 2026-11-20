import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { DailyCollectionTrack, DailyCollectionTrackStatus } from "../../lib/types";

/**
 * 패널 헤더 오른쪽의 수집 상태 한 줄(2026-11-20, ADR-0076 후속).
 *
 * `GET /api/daily-collection-status`의 서버 판정을 그대로 옮긴다. 화면은 기준일·상태를 다시 계산하지
 * 않는다. `complete`만 "수집 완료"이고, 나머지는 사실대로 쓰고 실행 상태로 가는 링크를 단다.
 * 조회 실패는 숨기지 않고 "확인할 수 없어요"로 말한다(돌았다고 가정하지 않는다).
 */
export const DAILY_COLLECTION_QUERY_KEY = ["daily-collection-status"] as const;

function monthDay(isoDate: string): string {
  return `${Number(isoDate.slice(5, 7))}월 ${Number(isoDate.slice(8, 10))}일`;
}

const STATE_LABEL: Record<DailyCollectionTrackStatus["state"], string> = {
  complete: "수집 완료",
  incomplete: "수집 확인 필요",
  missing: "수집 기록 없음",
};

function CheckIcon() {
  return <svg aria-hidden="true" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.6} viewBox="0 0 24 24"><path d="m5 12 5 5 9-10" /></svg>;
}

function WarnIcon() {
  return <svg aria-hidden="true" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} viewBox="0 0 24 24"><path d="M12 3 2 20h20z" /><path d="M12 10v4M12 17h.01" /></svg>;
}

export function CollectionStatus({ track }: { track: DailyCollectionTrack }) {
  const query = useQuery({
    queryKey: DAILY_COLLECTION_QUERY_KEY,
    queryFn: ({ signal }) => api.getDailyCollectionStatus({ signal }),
    staleTime: 60_000,
    retry: false,
  });
  if (query.isPending) return null;
  if (query.isError) {
    return (
      <span className="panel-header-status is-warning" data-state="error" data-testid="collection-status">
        <WarnIcon />
        <span><strong>수집 상태를 확인할 수 없어요</strong></span>
        <Link className="panel-header-status-link" to="/run-status">실행 상태</Link>
      </span>
    );
  }
  const status = query.data.tracks.find((item) => item.track === track);
  if (!status) {
    return (
      <span className="panel-header-status is-warning" data-state="error" data-testid="collection-status">
        <WarnIcon />
        <span><strong>수집 상태를 확인할 수 없어요</strong></span>
        <Link className="panel-header-status-link" to="/run-status">실행 상태</Link>
      </span>
    );
  }
  const complete = status.state === "complete";
  const warnings = status.state === "incomplete" && status.warning_count !== null ? ` · 적재 경고 ${status.warning_count}건` : "";
  return (
    <span
      className={`panel-header-status${complete ? "" : " is-warning"}`}
      data-state={status.state}
      data-testid="collection-status"
      title={status.latest_basis_date && status.latest_basis_date !== status.basis_date ? `기록이 있는 가장 늦은 기준일 ${monthDay(status.latest_basis_date)}` : undefined}
    >
      {complete ? <CheckIcon /> : <WarnIcon />}
      <span>
        <strong>{STATE_LABEL[status.state]}</strong>
        {` · ${monthDay(status.basis_date)} 기준${warnings}`}
      </span>
      {complete ? null : <Link className="panel-header-status-link" to="/run-status">실행 상태</Link>}
    </span>
  );
}

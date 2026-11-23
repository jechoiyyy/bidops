import { Link } from "react-router-dom";
import { StatusMark, type Mark } from "../common/Marks";
import type { DailyCollectionStatusResponse, DailyCollectionState } from "../../lib/types";

const STATUS_MARKS = {
  complete: { label: "수집 완료", tone: "neutral" },
  incomplete: { label: "적재 확인 필요", tone: "warning" },
  missing: { label: "수집 기록 없음", tone: "neutral" },
} satisfies Record<DailyCollectionState, Mark>;

export function CollectionStatus({ data, failed }: { data: DailyCollectionStatusResponse | undefined; failed: boolean }) {
  if (failed) return (
    <p className="dash-collection-status" role="status">
      일일 수집 상태를 불러오지 못했어요. <Link to="/run-status">실행 상태 보기</Link>
    </p>
  );
  if (!data) return <p className="dash-collection-status" role="status">일일 수집 상태를 확인하는 중이에요.</p>;

  return (
    <ul className="dash-collection-status" aria-label="기준일별 수집 상태">
      {data.tracks.map((track) => (
        <li key={track.track}>
          <span>{track.track === "order-plans" ? "발주계획" : "공고(사전규격·입찰공고)"}</span>
          <StatusMark mark={STATUS_MARKS[track.state]} />
          <span>{track.basis_date} 기준</span>
          {track.run_id && track.reasons.includes("ingest_warnings") ? (
            <Link to={`/audit?run=${encodeURIComponent(track.run_id)}#run-warnings`}>기준일 적재 경고 보기</Link>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

import { useEffect, useRef, type ReactNode } from "react";
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

const TRACK_SHORT: Record<string, string> = { "order-plans": "발주계획", notices: "공고" };

function trackPhrase(track: DailyCollectionStatusResponse["tracks"][number]): string {
  const name = TRACK_SHORT[track.track] ?? track.track;
  if (track.state === "missing") return `${name} 수집 기록 없음`;
  if (track.state === "incomplete") {
    return track.warning_count ? `${name} 적재 경고 ${track.warning_count.toLocaleString("ko-KR")}건` : `${name} 적재 확인 필요`;
  }
  return `${name} 수집 완료`;
}

/** 헤더의 수집 상태 한 줄. 누르면 트랙별 일일 수집 기록(`detail`)을 펼친다. */
export function CollectionHealth({ data, failed, detail }: { data: DailyCollectionStatusResponse | undefined; failed: boolean; detail: ReactNode }) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const close = (event: MouseEvent | KeyboardEvent) => {
      const node = ref.current;
      if (!node?.open) return;
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !node.contains(event.target as Node)) node.open = false;
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, []);
  let text: string;
  let warn: boolean;
  if (failed) { text = "수집 상태 미확인"; warn = true; }
  else if (!data) { text = "수집 상태 확인 중"; warn = false; }
  else {
    const dates = [...new Set(data.tracks.map(track => track.basis_date))];
    const basis = dates.length === 1 && dates[0] ? `${dates[0].slice(5)} 기준` : null;
    text = [basis, ...data.tracks.map(trackPhrase)].filter(Boolean).join(" · ");
    warn = data.tracks.some(track => track.state !== "complete");
  }
  return <details className="dash-health" data-state={warn ? "warning" : "ok"} ref={ref}>
    <summary aria-label={`일일 수집 상태: ${text}`}><span className="dash-health-led" aria-hidden="true" />{text}</summary>
    <div className="dash-health-pop">{detail}</div>
  </details>;
}

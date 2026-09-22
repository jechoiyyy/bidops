import { useEffect, useRef, useState } from "react";
import type { RunSummary } from "../../lib/types";
import { formatMomentShort, present, runStatusLabel } from "../../lib/format";
import { runOptionLabel } from "../../lib/runOptions";

interface BasisPopoverProps {
  run: RunSummary | null;
}

/**
 * 판정 기준선 전문은 길어서 상단 바에 그대로 두면 화면을 다 차지한다.
 * 기준선과 데이터 출처, 생성 시각을 눌러서 펼쳐 보는 팝오버로 옮긴다.
 */
export function BasisPopover({ run }: BasisPopoverProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div className="basis-popover" ref={containerRef}>
      <button
        aria-expanded={open}
        aria-controls="basis-popover-panel"
        className="basis-popover-trigger"
        type="button"
        onClick={() => setOpen((current) => !current)}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 11v5M12 8h.01" />
        </svg>
        판정 기준
      </button>
      {open ? (
        <div aria-label="판정 기준 상세" className="basis-popover-panel" id="basis-popover-panel" role="region">
          <dl className="facts facts-wide">
            <div className="fact-row">
              <dt>기준선</dt>
              <dd>{present(run?.screening_basis, "판정 기준 미기록")}</dd>
            </div>
            {/* 회차는 실무자가 아는 이름(`09-16~09-20 수집`)으로 부른다. 회차 식별자
                원문은 상단바에서 뺐고(ADR-0066 §3.3, 시안 M4) 주소와 운영 화면
                (`실행 상태 › 수집 실행`)에서 전문 그대로 읽는다 — 줄여서 적지 않는다.
                상태는 그대로 남긴다(대체된 회차를 현재 회차로 읽지 않게). */}
            <div className="fact-row">
              <dt>데이터 출처</dt>
              <dd>{run ? runOptionLabel(run) : "회차 미확인"} · {runStatusLabel(run?.status ?? "")}</dd>
            </div>
            <div className="fact-row">
              <dt>생성 시각</dt>
              <dd>{formatMomentShort(run?.generated_at)}</dd>
            </div>
          </dl>
        </div>
      ) : null}
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
import type { RunSummary } from "../../lib/types";
import { formatDateTime, present, runStatusLabel } from "../../lib/format";

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
        <div className="basis-popover-panel">
          <dl className="facts facts-wide">
            <div className="fact-row">
              <dt>기준선</dt>
              <dd>{present(run?.screening_basis, "판정 기준 미기록")}</dd>
            </div>
            <div className="fact-row">
              <dt>데이터 출처</dt>
              <dd className="mono">{present(run?.run_id, "회차 미확인")} · {runStatusLabel(run?.status ?? "")}</dd>
            </div>
            <div className="fact-row">
              <dt>생성 시각</dt>
              <dd>{formatDateTime(run?.generated_at)}</dd>
            </div>
          </dl>
        </div>
      ) : null}
    </div>
  );
}

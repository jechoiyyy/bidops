import { useEffect, useRef, useState, type ReactNode } from "react";
import { ListFilter, X } from "lucide-react";

const modes = { inline: "상단 펼침", dialog: "중앙 대화상자", popover: "버튼 아래 팝오버" } as const;
type Mode = keyof typeof modes;

const examples = [
  ["홈페이지 운영 및 유지관리", "일반용역", "독립 발견", "개요 완료", "완료", "미선택", 3, 1],
  ["도시 데이터 플랫폼 고도화", "기술용역", "발주계획 연결", "미시작", "진행 중", "계속 추적", 7, 0],
  ["통합 민원 시스템 운영", "일반용역", "독립 발견", "개요 완료", "완료", "보류", 10, 2],
  ["공공 데이터 품질 진단", "기술용역", "독립 발견", "사람 확인 필요", "실패", "미선택", 5, 3],
] as const;
const filterNames = ["업무구분", "발견 구분", "개요 상태", "자동 준비 상태", "추적 상태"];

export function OpeningComparison({ initialMode, grid, values, count, reset }: {
  initialMode: string; grid: ReactNode; values: Record<string, string>; count: number; reset: () => void;
}) {
  const [mode, setMode] = useState<Mode>(Object.hasOwn(modes, initialMode) ? initialMode as Mode : "inline");
  const [open, setOpen] = useState(true);
  const dialog = useRef<HTMLDialogElement>(null);
  const anchor = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  function close() { setOpen(false); trigger.current?.focus(); }
  useEffect(() => {
    if (mode === "dialog" && open) dialog.current?.showModal();
    if (!open) return;
    const escape = (e: KeyboardEvent) => { if (e.key === "Escape" && mode !== "dialog") close(); };
    const outside = (e: PointerEvent) => {
      if (mode === "popover" && !anchor.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", escape);
    document.addEventListener("pointerdown", outside);
    return () => {
      document.removeEventListener("keydown", escape);
      document.removeEventListener("pointerdown", outside);
    };
  }, [open, mode]);

  const rows = examples.filter(row => filterNames.every((key, i) => values[key] === "전체" || values[key] === row[i + 1]))
    .sort((a, b) => values["표시 순서"] === "최근 게시순" ? a[7] - b[7] : a[6] - b[6]);
  const panel = <div className="surface">
    <header className="sheet-head"><h2 id="opening-title">상세 필터</h2><button className="icon" aria-label="닫기" onClick={close}><X/></button></header>
    {grid}
    <footer><button className="reset" onClick={reset}>기본값으로</button><span>예시 결과 {rows.length}건</span><button className="primary" onClick={close}>완료</button></footer>
  </div>;
  return <main className="openings">
    <header><small>BidOps / 디자인 검토</small><h1>A안 · 필터 열기 방식</h1>
      <div className="mode-picker" role="group" aria-label="열기 방식">{(Object.keys(modes) as Mode[]).map(key =>
        <button key={key} aria-pressed={key === mode} onClick={() => { setMode(key); setOpen(true); }}>{modes[key]}</button>)}</div>
    </header>
    <section className="example">
      <div className="example-tools"><h2>사전규격 <small>예시 {rows.length}건</small></h2><div ref={anchor} className="anchor">
        <button className="filter-trigger" ref={trigger} aria-expanded={open} onClick={() => setOpen(v => !v)}><ListFilter size={17}/> 상세 필터 · {count}</button>
        {open && mode === "popover" && <section className="anchored" aria-labelledby="opening-title">{panel}</section>}
      </div></div>
      {open && mode === "inline" && <section className="inline-panel" aria-labelledby="opening-title">{panel}</section>}
      {open && mode === "dialog" && <dialog ref={dialog} className="central" aria-labelledby="opening-title"
        onCancel={e => { e.preventDefault(); close(); }} onClose={() => trigger.current?.focus()}>{panel}</dialog>}
      <table><thead><tr>{["사업명", "업무구분", "개요 상태", "추적 상태", "의견 마감"].map(v => <th key={v}>{v}</th>)}</tr></thead>
        <tbody>{rows.map(row => <tr key={row[0]}><td>{row[0]}</td><td>{row[1]}</td><td>{row[3]}</td><td>{row[5]}</td><td>D−{row[6]}</td></tr>)}
          {!rows.length && <tr><td colSpan={5}>조건에 맞는 예시가 없어요.</td></tr>}</tbody></table>
    </section>
  </main>;
}

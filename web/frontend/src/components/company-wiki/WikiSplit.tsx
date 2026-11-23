import { useLayoutEffect, useRef, type ReactNode } from "react";

export function WikiSplit({ list, selected, children }: { list: ReactNode; selected: string | null; children: ReactNode }) {
  const listRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    listRef.current?.querySelector("[aria-current]")?.scrollIntoView({ block: "nearest" });
  }, [selected]);
  return <div className="wiki-split"><div ref={listRef} className="wiki-list">{list}</div>
    <section key={selected} className="wiki-detail">{children}</section></div>;
}

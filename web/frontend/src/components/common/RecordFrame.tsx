import type { ReactNode } from "react";
import { usePageHeader, type PageHeaderContent } from "../shell/PageHeaderContext";

interface RecordFrameProps {
  /** The shell renders the only page title and keeps its route fallback. */
  heading: PageHeaderContent | null;
  intro?: ReactNode;
  rail?: ReactNode;
  railLabel?: string;
  children: ReactNode;
}

export function RecordFrame({ heading, intro, rail, railLabel, children }: RecordFrameProps) {
  usePageHeader(heading);
  return (
    <div className="workbench-record" data-layout={rail ? "rail" : "single"}>
      <div className="workbench-record-main">
        {intro ? <div className="workbench-record-intro">{intro}</div> : null}
        {children}
      </div>
      {rail ? <aside aria-label={railLabel} className="workbench-record-rail">{rail}</aside> : null}
    </div>
  );
}

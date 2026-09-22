import type { ReactNode } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { ArrowRight, CircleAlert, LoaderCircle, RefreshCw, Search } from "lucide-react";
import type { OpportunityListResponse } from "../../lib/types";
import { formatNumber } from "../../lib/format";
import { primaryTitle } from "../opportunities/trackingFlow";
import { DashboardPanel, LinkButton, Small } from "./DashboardPrimitives";
import { DueText, WorkRow } from "./WorkPanels";
import { HOLD_REVIEW_LIST_PATH, holdReviewDueText } from "./dashboardData";

/**
 * 보류 재검토 리마인드(spec §8·§11.2). 회차 선택과 무관한 누적 목록이며, 기한 지남과
 * 3일 이내 임박을 서버가 고르고 정렬한 순서대로 보여 준다. 이 패널은 추적 상태를
 * 바꾸지 않는다. 재검토 저장은 사업 추적 상세에서 한다.
 *
 * 행 모양은 다른 업무 패널과 같은 `WorkRow`다(S1). 표는 1280 반폭에서 마지막 열이
 * 가로로 밀려 났기 때문이고, 데이터·호출·건수 키·바닥 문구는 그대로다.
 */
export function HoldReviewPanel({ data, isPending, isError, onRetry, overdueNote, now }: {
  data: OpportunityListResponse | undefined; isPending: boolean; isError: boolean; onRetry: () => void;
  overdueNote: string; now: number;
}) {
  const items = data?.items ?? [];
  const summary = isError ? "건수 미확인" : isPending || !data ? "건수 확인 중"
    : items.length ? `기한 지남·임박 ${formatNumber(data.total)}건 중 ${formatNumber(items.length)}건 표시` : `기한 지남·임박 ${formatNumber(data.total)}건`;
  let body: ReactNode;
  if (isError) {
    body = <HoldReviewState kind="error" text="보류 재검토 목록을 불러오지 못했습니다."
      action={<Button label="보류 재검토 다시 조회" size="sm" icon={<RefreshCw aria-hidden="true" />} onClick={onRetry} />} />;
  } else if (isPending || !data) {
    body = <HoldReviewState kind="loading" text="보류 재검토 목록을 불러오는 중입니다." />;
  } else if (!items.length) {
    body = <HoldReviewState kind="empty" text="재검토가 필요한 보류 사업이 없습니다." />;
  } else {
    // 사유와 선택자는 값이 없을 때 서로 다른 말로 남긴다 — 빈 값을 다른 사람이나
    // 다른 사유로 바꾸지 않는다.
    body = <ul className="dash-work-list">{items.map(item => {
      const due = holdReviewDueText(item, now);
      return <WorkRow key={item.id} to={`/opportunities/${item.id}`} title={primaryTitle(item)}
        meta={`${item.tracking_reason?.trim() || "사유 미확인"} · ${item.tracking_selected_by?.trim() || "선택자 미확인"}`}
        end={<DueText text={due.text} urgent={due.urgent} />} />;
    })}</ul>;
  }
  return <DashboardPanel title="보류 재검토" caption="보류는 선택 후 14일이 지나면 다시 검토합니다." className="dash-hold-panel"
    action={<Small>{overdueNote}</Small>}
    footer={<><Small>{summary}</Small><LinkButton label="사업 추적에서 모두 보기" to={HOLD_REVIEW_LIST_PATH} icon={<ArrowRight aria-hidden="true" />} /></>}>
    {body}
  </DashboardPanel>;
}

function HoldReviewState({ kind, text, action }: { kind: "empty" | "loading" | "error"; text: string; action?: ReactNode }) {
  const Icon = kind === "error" ? CircleAlert : kind === "loading" ? LoaderCircle : Search;
  return <div className={`dash-hold-state dash-hold-state-${kind}`} role={kind === "error" ? "alert" : "status"}>
    <Icon aria-hidden="true" /><Text>{text}</Text>{action}
  </div>;
}

import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import { Badge } from "../common/Badge";
import { EmptyState } from "../common/EmptyState";
import { Panel } from "../common/Panel";
import { api } from "../../lib/api";
import { formatDate, present } from "../../lib/format";
import type { RelatedNoticeRelation } from "../../lib/types";
import { gradeVariant } from "../../lib/grade";

interface RelatedNoticesProps {
  noticePk: number;
}

function relationLabel(relation: RelatedNoticeRelation): string {
  if (relation === "ordinal") return "같은 공고 · 다른 차수";
  if (relation === "unified") return "같은 사업";
  return "같은 사전규격에서 파생";
}


export function RelatedNotices({ noticePk }: RelatedNoticesProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const relatedQuery = useQuery({
    queryKey: ["notice-related", noticePk],
    queryFn: () => api.getRelatedNotices(noticePk),
    staleTime: 30_000,
  });
  const items = relatedQuery.data?.items ?? [];

  return (
    <Panel className="related-notices-panel" title="관련 공고" action={<span className="panel-note">같은 회차 기준</span>}>
      {relatedQuery.isLoading ? <div className="inline-loading" role="status" aria-live="polite">관련 공고를 찾는 중입니다.</div> : null}
      {relatedQuery.error ? <div className="inline-error" role="alert">관련 공고를 불러오지 못했습니다.</div> : null}
      {!relatedQuery.isLoading && !relatedQuery.error && items.length === 0 ? <EmptyState compact title="관련 공고가 없습니다." description="비어 있는 식별자는 연결 기준으로 사용하지 않습니다." /> : null}
      {items.length > 0 ? (
        <div className="related-notice-list">
          {items.map((item) => (
            <button
              className="related-notice-row"
              key={item.notice_pk}
              type="button"
              onClick={() => navigate({ pathname: `/judgments/${item.notice_pk}`, search: location.search })}
            >
              <span className="related-notice-main">
                <span className="related-notice-title">{present(item.title, "공고명 미확인")}</span>
                <span className="related-notice-meta">
                  <Badge label={relationLabel(item.relation)} variant="focus" />
                  <Badge label={item.grade} variant={gradeVariant(item.grade)} />
                  <span className="mono tabular-nums">{item.published_at ? formatDate(item.published_at) : "공고일 미확인"}</span>
                </span>
                <span className="related-notice-key mono tabular-nums">{present(item.notice_key, "식별자 미확인")}</span>
                <span className="related-notice-reason">정정 사유: {present(item.change_reason, "없음")}</span>
              </span>
              <svg className="related-notice-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
                <path d="M5 12h13M13 6l6 6-6 6" />
              </svg>
            </button>
          ))}
        </div>
      ) : null}
    </Panel>
  );
}

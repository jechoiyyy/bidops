import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { companyContextQueryKey, getCompanyContext } from "../../lib/companyApi";
import { engineApi, engineKeys, type EngineRun } from "../../lib/engineApi";

export { PreSpecAnalysisWorkbench } from "./PreSpecAnalysisWorkbench";

/** 지금 보이는 사전규격의 엔진 run을 읽어 분석 완료 화면을 그릴지 알린다. 엔진 mock 패널과 같은 query key다. */
export function PreSpecEngineAnalysisProbe({ noticeId, onChange }: { noticeId: number; onChange: (run: EngineRun | null) => void }) {
  const company = useQuery({ queryKey: companyContextQueryKey, queryFn: ({ signal }) => getCompanyContext({ signal }), retry: false });
  const companyId = company.data?.company.company_id ?? null;
  const list = useQuery({
    queryKey: engineKeys.list(companyId ?? "", noticeId),
    queryFn: ({ signal }) => engineApi.list(companyId as string, noticeId, { signal }),
    enabled: companyId !== null,
    retry: false,
    refetchInterval: (query) => query.state.data?.items.some((run) => run.status === "queued" || run.status === "running") ? 2500 : false,
  });
  const latestId = list.data?.items[0]?.id ?? null;
  const detail = useQuery({
    queryKey: engineKeys.detail(companyId ?? "", noticeId, latestId),
    queryFn: ({ signal }) => engineApi.get(latestId as string, { signal }),
    enabled: companyId !== null && latestId !== null,
    retry: false,
  });
  const run = detail.data;
  const usable = run !== undefined && run.company_id === companyId && run.notice_id === noticeId
    && (run.status === "completed" || run.status === "partial") && run.analysis !== null;
  useEffect(() => {
    onChange(usable ? run : null);
  }, [onChange, run, usable]);
  return null;
}

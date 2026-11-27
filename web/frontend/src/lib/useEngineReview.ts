import { useQuery, type QueryClient } from "@tanstack/react-query";
import { engineReviewApi } from "./engineReviewApi";

export const engineReviewKey = (noticeId: number | null) => ["engine-review", noticeId] as const;

export function useEngineReview(noticeId: number | null, enabled: boolean, poll = true) {
  return useQuery({
    queryKey: engineReviewKey(noticeId),
    queryFn: ({ signal }) => engineReviewApi.get(noticeId as number, { signal }),
    enabled: enabled && noticeId !== null,
    staleTime: 2500,
    retry: false,
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      return poll && (state === "preparing" || state === "queued" || state === "running") ? 2500 : false;
    },
  });
}

export async function refreshEngineReview(queryClient: QueryClient, noticeId: number) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: engineReviewKey(noticeId) }),
    queryClient.invalidateQueries({ queryKey: ["workload"] }),
  ]);
}

/** The server can make previously ineligible notices eligible for source preparation. */
export async function refreshEngineReviewAfterRequests(queryClient: QueryClient, noticeIds: readonly number[]) {
  if (noticeIds.length === 0) return;
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["pre-specs"] }),
    queryClient.invalidateQueries({ queryKey: ["workload"] }),
    ...noticeIds.flatMap((noticeId) => [
      queryClient.invalidateQueries({ queryKey: engineReviewKey(noticeId) }),
      queryClient.invalidateQueries({ queryKey: ["pre-spec-detail", noticeId] }),
      queryClient.invalidateQueries({ queryKey: ["pre-spec-notice", noticeId] }),
      queryClient.invalidateQueries({ queryKey: ["document-bundles", noticeId] }),
    ]),
  ]);
}

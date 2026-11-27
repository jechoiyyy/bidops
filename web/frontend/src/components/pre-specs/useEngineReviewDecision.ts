import { useMutation, useMutationState, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { requestActorInput } from "../common/ActorField";
import { engineReviewApi, type EngineReviewOrigin } from "../../lib/engineReviewApi";
import { useFeatureFlags } from "../../lib/featureFlags";
import { generateRequestId } from "../../lib/requestId";
import { refreshEngineReviewAfterRequests, useEngineReview } from "../../lib/useEngineReview";

interface RequestIntent {
  noticeId: number;
  requestId: string;
  origin: EngineReviewOrigin;
  actor: string;
}

export function useEngineReviewDecision(noticeId: number | null, active: boolean, actor: string) {
  const flags = useFeatureFlags();
  const enabled = active && flags.engineReviewMode !== "off";
  const queryClient = useQueryClient();
  const query = useEngineReview(noticeId, enabled);
  const view = enabled ? query.data : undefined;
  const mutationKey = ["request-engine-review", noticeId];
  const [previewActor, setPreviewActor] = useState<string | null>(null);

  const requests = useMutationState({
    filters: { mutationKey, exact: true },
    select: (mutation) => ({
      intent: mutation.state.variables as RequestIntent | undefined,
      status: mutation.state.status,
      error: mutation.state.error,
    }),
  });
  const lastRequest = enabled ? requests.at(-1) : undefined;
  const requestFailure = lastRequest?.status === "error" ? lastRequest : null;
  const request = useMutation({
    mutationKey,
    mutationFn: ({ noticeId: id, requestId, origin, actor: name }: RequestIntent) =>
      engineReviewApi.request(id, { request_id: requestId, origin }, name),
    onSuccess: (_, intent) => refreshEngineReviewAfterRequests(queryClient, [intent.noticeId]),
  });

  async function requestReview(origin: EngineReviewOrigin, name = actor) {
    if (!enabled || noticeId === null || request.isPending || lastRequest?.status === "pending") return false;
    const clean = name.trim();
    if (!clean) {
      requestActorInput();
      return false;
    }
    const previous = requestFailure?.intent;
    // A retry replays the full command, including its audit actor and origin.
    const intent = previous?.origin === origin && previous.actor === clean
      ? previous : { noticeId, actor: clean, origin, requestId: generateRequestId() };
    try {
      await request.mutateAsync(intent);
      return true;
    } catch {
      return false;
    }
  }

  function openPreview() {
    if (!actor.trim()) requestActorInput();
    else setPreviewActor(actor.trim());
  }

  return {
    enabled, flagsPending: active && !flags.settled, view,
    queryError: query.isError, retryQuery: () => { void query.refetch(); },
    requestReview, requestPending: lastRequest?.status === "pending", requestFailure,
    retryRequest: () => { if (requestFailure?.intent) void requestReview(requestFailure.intent.origin); },
    previewActor, openPreview, closePreview: () => setPreviewActor(null),
  };
}

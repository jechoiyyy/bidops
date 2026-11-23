import { useQuery } from "@tanstack/react-query";
import { ApiError, api } from "../../lib/api";

export function useProfileSnapshotRegistration(error: unknown) {
  const snapshotUnavailable = error instanceof ApiError
    && error.status === 503
    && error.detail === "profile_snapshot_unavailable";
  const snapshots = useQuery({
    queryKey: ["profile-snapshots"],
    queryFn: api.getProfileSnapshots,
    enabled: snapshotUnavailable,
    retry: false,
    staleTime: 30_000,
  });
  return {
    missing: snapshotUnavailable && snapshots.isSuccess
      && snapshots.data.total === 0 && Array.isArray(snapshots.data.items) && snapshots.data.items.length === 0,
    checking: snapshotUnavailable && snapshots.isPending,
    refetch: snapshotUnavailable ? snapshots.refetch : undefined,
  };
}

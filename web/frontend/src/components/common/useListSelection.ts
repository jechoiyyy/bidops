import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  applySelectionResult,
  clearSelection,
  createEmptyListSelection,
  getListSelectionStorage,
  readListSelection,
  nextSelectionGeneration,
  resetSelectionForFilter,
  setSelectionActiveId,
  setSelectionContext,
  toggleSelection,
  updateSelectionSortMetadata,
  writeListSelection,
  type ListSelectionId,
  type ListSelectionState,
  type ListSelectionStorage,
  type ListSelectionStorageError,
  type ListSelectionValidationOptions,
  type ListSelectionWriteResult,
} from "../../lib/listSelection";

export interface UseListSelectionOptions<Id extends ListSelectionId = ListSelectionId, Metadata = unknown> {
  /** A distinct key is required for each list surface. */
  storageKey: string;
  /** The already-applied semantic filter fingerprint; page/sort are excluded. */
  filterFingerprint: string;
  /** Optional storage injection for tests or an embedding shell. */
  storage?: ListSelectionStorage | null;
  /** Deep links can make URL context authoritative and skip restoration. */
  restoreStoredState?: boolean;
  /**
   * Effective URL context must be ready before storage is read. For example,
   * the order-plan source run is resolved asynchronously; pass false while it
   * is unresolved so a provisional fingerprint cannot clear a stored set.
   */
  hydrationReady?: boolean;
  initial?: Partial<Omit<ListSelectionState<Id, Metadata>, "version" | "filterFingerprint">>;
  isValidMetadata?: (value: unknown, id: Id) => value is Metadata;
}

export interface UseListSelectionResult<Id extends ListSelectionId = ListSelectionId, Metadata = unknown> {
  state: ListSelectionState<Id, Metadata>;
  selectedIds: readonly Id[];
  selectedIdSet: ReadonlySet<Id>;
  activeId: Id | null;
  hydrated: boolean;
  /** Storage has been read for the effective filter context. */
  hydrationReady: boolean;
  /** False when sessionStorage cannot be reached; callers must not claim refresh recovery. */
  storageAvailable: boolean;
  storageError: ListSelectionStorageError | null;
  toggle: (id: Id, metadata?: Metadata) => void;
  clear: () => void;
  setActiveId: (id: Id | null) => void;
  setListSearch: (value: string) => void;
  setListScrollTop: (value: number) => void;
  setSortMetadata: (id: Id, metadata: Metadata) => void;
  applyResult: (resolvedIds: readonly Id[], expectedGeneration?: number) => void;
  resetForFilter: (fingerprint: string) => void;
  /** Synchronously persist before a durable review/bulk request is sent. */
  persist: () => ListSelectionWriteResult;
}

export function useListSelection<Id extends ListSelectionId = ListSelectionId, Metadata = unknown>({
  storageKey,
  filterFingerprint,
  storage,
  restoreStoredState = true,
  hydrationReady: hydrationReadyProp = true,
  initial,
  isValidMetadata,
}: UseListSelectionOptions<Id, Metadata>): UseListSelectionResult<Id, Metadata> {
  const storageRef = useRef<ListSelectionStorage | null>(null);
  const storageKeyRef = useRef<string | null>(null);
  if (storageKeyRef.current !== storageKey) {
    storageKeyRef.current = storageKey;
    storageRef.current = storage === undefined ? getListSelectionStorage() : storage;
  }

  const initialState = useMemo(
    () => createEmptyListSelection<Id, Metadata>(filterFingerprint, {
      ...initial,
    }),
    // Initial context is a seed. Later URL context changes are applied by the
    // actions/effects below rather than silently replacing selected state.
    [filterFingerprint, initial, storageKey],
  );
  const [state, setState] = useState<ListSelectionState<Id, Metadata>>(initialState);
  const [hydrated, setHydrated] = useState(false);
  const [hydratedStorageKey, setHydratedStorageKey] = useState<string | null>(null);
  const [storageError, setStorageError] = useState<ListSelectionStorageError | null>(null);
  const hydratedKeyRef = useRef<string | null>(null);
  const filterFingerprintRef = useRef(filterFingerprint);
  const stateRef = useRef(state);
  stateRef.current = state;
  const updateState = useCallback(
    (updater: (current: ListSelectionState<Id, Metadata>) => ListSelectionState<Id, Metadata>) => {
      const next = updater(stateRef.current);
      stateRef.current = next;
      setState(next);
    },
    [],
  );

  useEffect(() => {
    if (!hydrationReadyProp) return;
    if (hydratedKeyRef.current === storageKey) return;
    hydratedKeyRef.current = storageKey;
    setHydrated(false);
    const result = readListSelection<Id, Metadata>(storageKey, storageRef.current, {
      isValidMetadata,
    } satisfies ListSelectionValidationOptions<Id, Metadata>);
    setStorageError(result.error);
    if (restoreStoredState && result.state && result.state.filterFingerprint === filterFingerprint) {
      stateRef.current = result.state;
      setState(result.state);
    } else if (result.state) {
      // URL/filter context wins on mismatch. Preserve only the generation fence
      // so a late result from the prior semantic filter cannot clear new picks.
      const next = createEmptyListSelection<Id, Metadata>(filterFingerprint, {
        ...initial,
        selectionGeneration: nextSelectionGeneration(result.state.selectionGeneration),
      });
      stateRef.current = next;
      setState(next);
    } else {
      stateRef.current = initialState;
      setState(initialState);
    }
    filterFingerprintRef.current = filterFingerprint;
    setHydrated(true);
    setHydratedStorageKey(storageKey);
  }, [
    filterFingerprint,
    initial,
    initialState,
    isValidMetadata,
    restoreStoredState,
    storageKey,
    hydrationReadyProp,
  ]);

  useEffect(() => {
    if (!hydrationReadyProp || !hydrated || hydratedKeyRef.current !== storageKey) return;
    if (filterFingerprintRef.current === filterFingerprint) return;
    filterFingerprintRef.current = filterFingerprint;
    updateState((current) => resetSelectionForFilter(current, filterFingerprint));
  }, [filterFingerprint, hydrated, hydrationReadyProp, storageKey, updateState]);

  useEffect(() => {
    if (!hydrationReadyProp || !hydrated || hydratedStorageKey !== storageKey || state.filterFingerprint !== filterFingerprint) return;
    const result = writeListSelection(storageKey, state, storageRef.current);
    if (!result.ok) setStorageError(result.error);
  }, [filterFingerprint, hydrated, hydratedStorageKey, hydrationReadyProp, state, storageKey]);

  const toggle = useCallback((id: Id, metadata?: Metadata) => {
    updateState((current) => toggleSelection(current, id, metadata));
  }, [updateState]);
  const clear = useCallback(() => {
    updateState((current) => clearSelection(current));
  }, [updateState]);
  const setActiveId = useCallback((id: Id | null) => {
    updateState((current) => setSelectionActiveId(current, id));
  }, [updateState]);
  const setListSearch = useCallback((value: string) => {
    updateState((current) => setSelectionContext(current, { listSearch: value }));
  }, [updateState]);
  const setListScrollTop = useCallback((value: number) => {
    updateState((current) => setSelectionContext(current, { listScrollTop: value }));
  }, [updateState]);
  const setSortMetadata = useCallback((id: Id, metadata: Metadata) => {
    updateState((current) => updateSelectionSortMetadata(current, id, metadata));
  }, [updateState]);
  const applyResult = useCallback((resolvedIds: readonly Id[], expectedGeneration?: number) => {
    updateState((current) => applySelectionResult(current, resolvedIds, expectedGeneration));
  }, [updateState]);
  const resetForFilter = useCallback((fingerprint: string) => {
    if (!hydrationReadyProp) return;
    filterFingerprintRef.current = fingerprint;
    updateState((current) => resetSelectionForFilter(current, fingerprint));
  }, [hydrationReadyProp, updateState]);
  const persist = useCallback((): ListSelectionWriteResult => {
    if (!hydrationReadyProp || !hydrated || hydratedStorageKey !== storageKey) {
      return {
        ok: false,
        error: {
          code: "invalid_state",
          message: "목록 선택 저장소가 현재 적용된 목록 조건에 맞게 준비되지 않았습니다.",
        },
      };
    }
    const result = writeListSelection(storageKey, stateRef.current, storageRef.current);
    if (!result.ok) setStorageError(result.error);
    return result;
  }, [hydrated, hydratedStorageKey, hydrationReadyProp, storageKey]);

  const selectedIdSet = useMemo(() => new Set(state.selectedIds), [state.selectedIds]);
  return {
    state,
    selectedIds: state.selectedIds,
    selectedIdSet,
    activeId: state.activeId,
    hydrated,
    hydrationReady: hydrationReadyProp && hydrated,
    storageAvailable: storageRef.current !== null
      && storageError?.code !== "storage_unavailable"
      && storageError?.code !== "storage_read_failed"
      && storageError?.code !== "storage_write_failed",
    storageError,
    toggle,
    clear,
    setActiveId,
    setListSearch,
    setListScrollTop,
    setSortMetadata,
    applyResult,
    resetForFilter,
    persist,
  };
}

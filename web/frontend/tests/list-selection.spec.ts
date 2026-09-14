import { expect, test } from "@playwright/test";
import {
  applySelectionResult,
  comparePreSpecMetadata,
  createEmptyListSelection,
  normalizeTimestamp,
  orderPlansFilterFingerprint,
  preSpecsFilterFingerprint,
  readListSelection,
  resetSelectionForFilter,
  setSelectionContext,
  sortOrderPlanItems,
  sortPreSpecMetadata,
  toggleSelection,
  validateListSelection,
  writeListSelection,
  isPreSpecSelectionSortMetadata,
  type ListSelectionState,
  type ListSelectionStorage,
  type PreSpecSelectionSortMetadata,
} from "../src/lib/listSelection";
import {
  createPreSpecSelectionReview,
  readPreSpecSelectionReview,
} from "../src/lib/preSpecSelectionReview";

class MemoryStorage implements ListSelectionStorage {
  private readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

class SessionStorageStub {
  private readonly values = new Map<string, string>();
  setCalls = 0;

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.setCalls += 1;
    if (this.throwOnSet) throw new Error("storage blocked");
    this.values.set(key, value);
  }

  throwOnSet = false;
}

function withGlobals<T>(
  cryptoValue: unknown,
  sessionStorageValue: unknown,
  callback: () => T,
): T {
  const cryptoDescriptor = Object.getOwnPropertyDescriptor(globalThis, "crypto");
  const sessionStorageDescriptor = Object.getOwnPropertyDescriptor(globalThis, "sessionStorage");
  Object.defineProperty(globalThis, "crypto", {
    configurable: true,
    writable: true,
    value: cryptoValue,
  });
  Object.defineProperty(globalThis, "sessionStorage", {
    configurable: true,
    writable: true,
    value: sessionStorageValue,
  });
  try {
    return callback();
  } finally {
    if (cryptoDescriptor) Object.defineProperty(globalThis, "crypto", cryptoDescriptor);
    else delete (globalThis as { crypto?: unknown }).crypto;
    if (sessionStorageDescriptor) Object.defineProperty(globalThis, "sessionStorage", sessionStorageDescriptor);
    else delete (globalThis as { sessionStorage?: unknown }).sessionStorage;
  }
}

function reviewInput() {
  return {
    orderedNoticeIds: [11, 7],
    listSearch: "sw_only=false&offset=20",
    filterFingerprint: "pre-specs:test",
    selectionGeneration: 2,
    entryNoticeId: 11,
  };
}

test("LS-S1 canonical fingerprints normalize set order and exclude paging context", () => {
  const first = orderPlansFilterFingerprint({
    sourceRunId: "run-a",
    qwen: ["uncertain", "relevant"],
    stage1: new Set(["failed", "selected"]),
    feedback: ["none", "has"],
    issue: true,
    q: "  접근성  ",
  });
  const reordered = orderPlansFilterFingerprint({
    q: "  접근성  ",
    issue: true,
    feedback: ["has", "none"],
    stage1: ["selected", "failed"],
    qwen: ["relevant", "uncertain"],
    sourceRunId: "run-a",
  });
  expect(first).toBe(reordered);
  expect(first).not.toContain("offset");
  expect(orderPlansFilterFingerprint({ ...reorderedInput(), q: "접근성" })).not.toBe(first);
  expect(preSpecsFilterFingerprint({
    swOnly: true,
    businessDivision: "",
    origin: "신규",
    grade: "",
    autoPreparationStatus: "",
    trackingDecision: "",
    view: "all",
    q: "",
  })).toBe(preSpecsFilterFingerprint({
    swOnly: true,
    businessDivision: "",
    origin: "신규",
    grade: "",
    autoPreparationStatus: "",
    trackingDecision: "",
    view: "all",
    q: "",
  }));
  expect(preSpecsFilterFingerprint({
    swOnly: true,
    businessDivision: "parser-already-normalized",
    origin: "신규",
    grade: "",
    autoPreparationStatus: "",
    trackingDecision: "",
    view: "all",
    q: "",
  })).not.toBe(preSpecsFilterFingerprint({
    swOnly: true,
    businessDivision: "",
    origin: "신규",
    grade: "",
    autoPreparationStatus: "",
    trackingDecision: "",
    view: "all",
    q: "",
  }));
});

function reorderedInput() {
  return {
    sourceRunId: "run-a",
    qwen: ["relevant", "uncertain"],
    stage1: ["selected", "failed"],
    feedback: ["has", "none"],
    issue: true,
    q: "  접근성  ",
  };
}

test("LS-S2 hydration validates version and IDs, deduplicates, and drops stale metadata", () => {
  const storage = new MemoryStorage();
  storage.setItem("selection", JSON.stringify({
    version: 1,
    filterFingerprint: "order-plans:{}",
    selectionGeneration: 4,
    selectedIds: [12, 12, 13],
    selectedSortMetadata: { "12": { relevance: "raw" }, "999": { secret: true } },
    listSearch: "source_run_id=run-a",
    activeId: 12,
    listScrollTop: 88,
  }));
  const result = readListSelection("selection", storage);
  expect(result.status).toBe("restored");
  expect(result.state?.selectedIds).toEqual([12, 13]);
  expect(result.state?.selectedSortMetadata).toEqual({ "12": { relevance: "raw" } });

  storage.setItem("selection", JSON.stringify({
    version: 1,
    filterFingerprint: "order-plans:{}",
    selectionGeneration: 4,
    selectedIds: [12, "12"],
    selectedSortMetadata: {},
    listSearch: "",
    activeId: null,
    listScrollTop: 0,
  }));
  expect(readListSelection("selection", storage).status).toBe("invalid");
  expect(validateListSelection({ version: 99 }).state).toBeNull();
});

test("LS-S3 storage failures are explicit and do not masquerade as recovery", () => {
  const unavailable = readListSelection("selection", null);
  expect(unavailable.status).toBe("unavailable");
  expect(unavailable.error?.code).toBe("storage_unavailable");

  const throwingStorage: ListSelectionStorage = {
    getItem: () => {
      throw new Error("blocked");
    },
    setItem: () => {
      throw new Error("quota");
    },
  };
  expect(readListSelection("selection", throwingStorage).error?.code).toBe("storage_read_failed");
  const state = createEmptyListSelection("order-plans:{}");
  const writeResult = writeListSelection("selection", state, throwingStorage);
  expect(writeResult.ok).toBe(false);
  expect(writeResult.error?.code).toBe("storage_write_failed");
});

test("LS-S4 filter generations fence stale results and preserve failed IDs", () => {
  let state = createEmptyListSelection<number, { source: string }>("same");
  state = toggleSelection(state, 12, { source: "list" });
  state = toggleSelection(state, 13, { source: "list" });
  expect(state.selectedIds).toEqual([12, 13]);

  const changed = resetSelectionForFilter(state, "changed");
  expect(changed.selectionGeneration).toBe(1);
  expect(changed.selectedIds).toEqual([]);
  state = toggleSelection(changed, 12, { source: "retry" });
  expect(applySelectionResult(state, [12], 0).selectedIds).toEqual([12]);
  expect(applySelectionResult(state, [], state.selectionGeneration).selectedIds).toEqual([12]);
  expect(applySelectionResult(state, [12], state.selectionGeneration).selectedIds).toEqual([]);
});

test("LS-S5 order-plan relevance sorting is deterministic and does not use click order", () => {
  const items = sortOrderPlanItems([
    { order_plan_pk: 4, qwen_relevance: null },
    { order_plan_pk: 2, qwen_relevance: "uncertain" },
    { order_plan_pk: 1, qwen_relevance: "relevant" },
    { order_plan_pk: 3, qwen_relevance: "relevant" },
  ]);
  expect(items.map((item) => item.order_plan_pk)).toEqual([1, 3, 2, 4]);
});

test("PN-S2 pre-spec ordering preserves timezone offsets and microseconds", () => {
  const newer: PreSpecSelectionSortMetadata = {
    id: 1,
    published_at: "2026-01-01T00:00:00.000002Z",
    deadline_at: null,
  };
  const older: PreSpecSelectionSortMetadata = {
    id: 2,
    published_at: "2026-01-01T09:00:00.000001+09:00",
    deadline_at: null,
  };
  // Date.parse would collapse these to the same millisecond; the comparator
  // retains the microsecond difference.
  expect(normalizeTimestamp(newer.published_at)).not.toBe(normalizeTimestamp(older.published_at));
  expect(comparePreSpecMetadata(newer, older, "published")).toBeLessThan(0);

  const equalInstantHighPk: PreSpecSelectionSortMetadata = {
    id: 9,
    published_at: "2026-01-01 09:00:00.000001+09:00",
    deadline_at: null,
  };
  expect(comparePreSpecMetadata(equalInstantHighPk, older, "published")).toBeLessThan(0);

  const deadlineRows: PreSpecSelectionSortMetadata[] = [
    { id: 8, published_at: null, deadline_at: null },
    { id: 3, published_at: null, deadline_at: "2026-01-03T00:00:00.000001Z" },
    { id: 2, published_at: null, deadline_at: "2026-01-03T00:00:00.000001Z" },
  ];
  expect(sortPreSpecMetadata(deadlineRows, "deadline").map((item) => item.id)).toEqual([2, 3, 8]);
  expect(normalizeTimestamp("2026-01-03T00:00:00.000001")).toBeNull();
  expect(normalizeTimestamp("0000-01-03T00:00:00Z")).toBeNull();
  expect(normalizeTimestamp("2026-02-29T00:00:00Z")).toBeNull();
  expect(() => sortPreSpecMetadata([
    { id: 1, published_at: null, deadline_at: "2026-01-03T00:00:00.000001" },
  ], "deadline")).toThrow();
  expect(isPreSpecSelectionSortMetadata({
    id: 1,
    published_at: "2026-01-03T00:00:00Z",
    deadline_at: "2026-01-03T00:00:00",
  })).toBe(false);
  const malformedState = {
    version: 1,
    filterFingerprint: "pre-specs:{}",
    selectionGeneration: 0,
    selectedIds: [1],
    selectedSortMetadata: {
      "1": {
        id: 1,
        published_at: "2026-01-03T00:00:00Z",
        deadline_at: "2026-01-03T00:00:00",
      },
    },
    listSearch: "",
    activeId: null,
    listScrollTop: 0,
  };
  expect(validateListSelection(malformedState).error).not.toBeNull();
  const storage = new MemoryStorage();
  storage.setItem("malformed-pre-spec", JSON.stringify(malformedState));
  expect(readListSelection("malformed-pre-spec", storage).status).toBe("invalid");
});

test("LS-S6 selected state keeps active row and checked membership independent", () => {
  const state: ListSelectionState<number, undefined> = {
    ...createEmptyListSelection<number, undefined>("fp"),
    activeId: 2,
  };
  const checked = toggleSelection(state, 1);
  expect(checked.activeId).toBe(2);
  expect(checked.selectedIds).toEqual([1]);
  expect(toggleSelection(checked, 1).activeId).toBe(2);
});

test("LS-S7 unchanged list context preserves the state object", () => {
  const state = createEmptyListSelection("fp", { activeId: 2, listSearch: "q=x", listScrollTop: 12 });
  expect(setSelectionContext(state, { activeId: 2, listSearch: "q=x", listScrollTop: 12 })).toBe(state);
});

test("PN-S3 selection review uses getRandomValues when randomUUID is unavailable", () => {
  const storage = new SessionStorageStub();
  const cryptoWithoutRandomUUID = {
    getRandomValues(bytes: Uint8Array): Uint8Array {
      bytes.set([0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,
        0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f]);
      return bytes;
    },
  };
  const outcome = withGlobals(cryptoWithoutRandomUUID, storage, () => {
    const created = createPreSpecSelectionReview(reviewInput());
    const restored = created.ok
      ? readPreSpecSelectionReview(`?selection_review=${created.value.reviewId}`, 11)
      : null;
    return { created, restored };
  });

  expect(outcome.created.ok).toBe(true);
  if (!outcome.created.ok) throw new Error(outcome.created.error);
  expect(outcome.created.value.reviewId).toMatch(
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
  );
  const sections = outcome.created.value.reviewId.split("-");
  expect(Number.parseInt(sections[2][0], 16)).toBe(4);
  expect(Number.parseInt(sections[3][0], 16) & 0x0c).toBe(0x08);
  expect(outcome.restored).toEqual(outcome.created.value);
  expect(storage.setCalls).toBe(1);
});

test("PN-S4 secure randomness failure is distinct and does not write review storage", () => {
  const storage = new SessionStorageStub();
  const outcome = withGlobals({ randomUUID: undefined, getRandomValues: undefined }, storage, () =>
    createPreSpecSelectionReview(reviewInput()));

  expect(outcome.ok).toBe(false);
  if (outcome.ok) throw new Error("secure randomness unexpectedly succeeded");
  expect(outcome.error).toContain("보안 난수");
  expect(outcome.error).not.toContain("저장");
  expect(storage.setCalls).toBe(0);
});

test("PN-S5 selection review keeps storage denial separate from ID generation", () => {
  const storage = new SessionStorageStub();
  storage.throwOnSet = true;
  const outcome = withGlobals({
    getRandomValues(bytes: Uint8Array): Uint8Array {
      bytes.fill(0);
      return bytes;
    },
  }, storage, () => createPreSpecSelectionReview(reviewInput()));

  expect(outcome.ok).toBe(false);
  if (outcome.ok) throw new Error("storage denial unexpectedly succeeded");
  expect(outcome.error).toContain("저장하지 못했습니다");
  expect(outcome.error).not.toContain("보안 난수");
  expect(storage.setCalls).toBe(1);
});

import { createContext, useContext, useEffect, type Dispatch, type SetStateAction } from "react";
import type { RouteCrumb } from "./route-meta";

/**
 * 사업기회 레코드의 상단 경로 마지막 칸(레코드 제목)을 셸에 알리는 context(RL-02 spec).
 *
 * route-meta의 `record.label`은 route param만 읽는 동기 함수이고 셸에서 TopBar까지는 props뿐이라
 * 활동 응답의 제목을 거기서 읽을 수 없다. 그래서 레코드 페이지가 응답 `title`을 이 context에
 * 넣고, `AppShell`이 **현재 match의 `opportunityId`와 같을 때만** 그 칸의 라벨을 덮어쓴다.
 * 제목이 오기 전이거나 다른 레코드의 값이 남아 있으면 route의 `#<id>`가 그대로 보인다.
 */
export interface RecordTitle {
  opportunityId: number;
  title: string;
}

export type RecordTitleValue = RecordTitle | null;

export const RecordTitleContext = createContext<RecordTitleValue>(null);
export const RecordTitleSetterContext = createContext<Dispatch<SetStateAction<RecordTitleValue>> | null>(null);

/** 레코드 페이지가 제목을 셸에 올린다. 떠날 때(또는 레코드가 바뀔 때) 비운다. */
export function usePublishRecordTitle(opportunityId: number | null, title: string | null): void {
  const set = useContext(RecordTitleSetterContext);
  useEffect(() => {
    if (!set || opportunityId === null || !title) return undefined;
    set({ opportunityId, title });
    return () => set((current) => (current?.opportunityId === opportunityId ? null : current));
  }, [set, opportunityId, title]);
}

/**
 * 현재 match의 `opportunityId`와 context 값이 같을 때만 `record` 칸의 라벨을 바꾼다.
 * 병합된 레코드를 떠나 다른 레코드로 갈 때 이전 제목이 잠깐 남아도 일치하지 않으면 쓰지 않는다.
 */
export function applyRecordTitle(
  crumbs: RouteCrumb[],
  params: Readonly<Record<string, string | undefined>>,
  value: RecordTitleValue,
): RouteCrumb[] {
  if (!value || params.opportunityId !== String(value.opportunityId)) return crumbs;
  return crumbs.map((crumb) => (crumb.role === "record" ? { ...crumb, label: value.title } : crumb));
}

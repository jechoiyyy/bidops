import { ApiError } from "../../lib/api";

export function wikiValue(value: string | number | null) {
  if (value === "unknown") return "미확인";
  return value ?? "값 없음";
}

export function WikiState({ error }: { error: Error | null }) {
  if (!error) return <p role="status">회사 근거를 불러오고 있어요.</p>;
  if (error instanceof ApiError) {
    switch (error.code) {
      case "company_wiki_unavailable":
        return <p>회사 위키가 아직 연결되지 않았어요. 운영 설정에서 회사 묶음 폴더(BIDOPS_ENGINE_COMPANY_BUNDLE_DIR)와 회사 식별자(BIDOPS_ENGINE_COMPANY_BUNDLE_SLUG)를 지정해 주세요.</p>;
      case "company_wiki_work_units_unavailable":
        return <p>업무별 근거 지도가 아직 없어요.</p>;
      case "company_wiki_project_not_found":
        return <p>선택한 실적을 찾을 수 없어요.</p>;
      case "company_wiki_topic_not_found":
        return <p>선택한 주제를 찾을 수 없어요.</p>;
      case "company_wiki_page_not_found":
        return <p>선택한 페이지를 찾을 수 없어요.</p>;
      case "company_wiki_unreadable":
        return <p role="alert">회사 위키를 읽을 수 없어요. 회사 묶음의 파일 형식을 확인해 주세요.</p>;
    }
  }
  return <p role="alert">회사 근거를 불러오지 못했어요.</p>;
}

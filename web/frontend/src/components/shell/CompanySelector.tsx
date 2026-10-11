import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import { Badge } from "../common/Badge";
import { COMPANY_DIRECTORY_LIMIT, companyApi, companyKeys } from "../../lib/companyApi";
import "../../styles/company-workspace.css";

/**
 * 회사를 바꿀 때 갈 주소.
 *
 * 주소가 정본이다(새로고침·뒤로가기). 같은 자원이 새 회사에도 뜻이 있으면 그
 * 자원으로, 아니면 새 회사의 사전규격 목록으로 간다.
 *
 * - 목록 → 목록, 프로필 → 프로필
 * - 사전규격 상세 → 같은 공고의 새 회사 상세(원문 공고는 회사와 무관하게 공유한다)
 * - 심층 검토 보고서 → 새 회사 목록(보고서 ID는 회사 소유라 다른 회사에는 없다)
 * - 3사 비교 → 같은 공고의 새 회사 상세
 * - 그 밖(회사 선택·기존 화면) → 새 회사 목록
 *
 * 검색 인자는 넘기지 않는다. 선택·순회 상태는 회사별 `sessionStorage`가 복원한다.
 */
export function companySwitchTarget(pathname: string, nextCompanyId: string): string {
  const base = `/companies/${nextCompanyId}`;
  const company = pathname.match(/^\/companies\/[^/]+(\/.*)?$/);
  if (company) {
    const rest = company[1] ?? "";
    if (rest === "/profile") return `${base}/profile`;
    const detail = rest.match(/^\/pre-specs\/([1-9][0-9]*)$/);
    if (detail) return `${base}/pre-specs/${detail[1]}`;
    return `${base}/pre-specs`;
  }
  const comparison = pathname.match(/^\/pre-specs\/([1-9][0-9]*)\/company-comparison$/);
  if (comparison) return `${base}/pre-specs/${comparison[1]}`;
  return `${base}/pre-specs`;
}

/**
 * 상단바의 회사 선택기와 데모 표식. `GET /api/demo-config`가 enabled일 때만 셸이 그린다.
 *
 * 값은 주소의 `companyId`에서만 온다(controlled). 바꾸면 이동만 하고, 이동이 화면의
 * 미저장 입력 확인(`useUnsavedGuard`)에서 취소되면 주소가 그대로라 선택도 그대로다.
 * 회사가 정해지지 않은 주소에서는 빈 선택으로 두며 기본 회사를 고르지 않는다.
 */
export function CompanySelector({ companyId }: { companyId: string | null }) {
  const navigate = useNavigate();
  const location = useLocation();
  const companiesQuery = useQuery({
    queryKey: companyKeys.directory(),
    queryFn: ({ signal }) => companyApi.listCompanies({ limit: COMPANY_DIRECTORY_LIMIT, offset: 0 }, { signal }),
    staleTime: 60_000,
  });
  const companies = companiesQuery.data?.items ?? [];
  const known = companyId !== null && companies.some((company) => company.company_id === companyId);

  return (
    <div className="company-switcher" data-testid="company-switcher">
      <Badge className="demo-marker" variant="info" label="가상회사 데모" role="note" aria-label="가상회사 데모 화면" />
      <label className="run-selector company-selector">
        <span className="run-selector-label">회사</span>
        <select
          aria-label="데모 회사 선택"
          disabled={companiesQuery.isPending || companiesQuery.isError}
          value={companyId ?? ""}
          onChange={(event) => {
            const next = event.target.value;
            if (!next || next === companyId) return;
            navigate(companySwitchTarget(location.pathname, next));
          }}
        >
          {companyId === null ? <option value="">회사를 고르십시오</option> : null}
          {companyId !== null && !known ? (
            <option value={companyId}>{companiesQuery.isPending ? "회사 확인 중" : "확인되지 않은 회사"}</option>
          ) : null}
          {companies.map((company) => (
            <option key={company.company_id} value={company.company_id}>
              {company.name}
            </option>
          ))}
        </select>
        <svg className="select-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="m6 9 6 6 6-6" />
        </svg>
      </label>
      {companiesQuery.isError ? <span className="company-switcher-error" role="status">회사 목록을 불러오지 못했습니다</span> : null}
    </div>
  );
}

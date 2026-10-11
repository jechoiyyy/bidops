import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Badge } from "../common/Badge";
import { EmptyState } from "../common/EmptyState";
import { describeCompanyApiError } from "../../lib/apiErrors";
import { companyApi, companyKeys, type Uuid } from "../../lib/companyApi";
import "../../styles/company-workspace.css";

export type CompanyScreen = "pre-specs" | "profile" | "pre-spec-detail" | "deep-review";

/**
 * 회사 화면 맨 위의 회사 머리글.
 *
 * 회사 identity는 주소의 `companyId`로 `GET /api/companies/{id}`를 읽어 그린다. 다른
 * 회사의 cache를 빌려 쓰지 않으며(`companyKeys.detail`), 읽는 중에는 이전 회사 이름을
 * 남기지 않고 읽는 중임을 말한다. `is_fictional`은 서버 값 그대로 표시한다.
 */
export function CompanyHeader({ companyId, screen }: { companyId: Uuid; screen: CompanyScreen }) {
  const companyQuery = useQuery({
    queryKey: companyKeys.detail(companyId),
    queryFn: ({ signal }) => companyApi.getCompany(companyId, { signal }),
    retry: false,
  });

  if (companyQuery.isPending) {
    return (
      <header className="cw-company-header" aria-busy="true" aria-label="선택한 회사" data-company-id={companyId} data-testid="company-header">
        <p role="status">회사 정보를 불러오는 중입니다.</p>
      </header>
    );
  }
  if (companyQuery.isError) {
    return (
      <EmptyState
        tone="error"
        title="회사 정보를 확인할 수 없습니다."
        problem={describeCompanyApiError(companyQuery.error, "회사 정보를 불러오지 못했습니다.")}
        action={{ label: "회사 다시 고르기", to: "/companies" }}
      />
    );
  }
  const company = companyQuery.data;
  const base = `/companies/${companyId}`;
  return (
    <header className="cw-company-header" aria-label="선택한 회사" data-company-id={company.company_id} data-testid="company-header">
      <div className="cw-company-identity">
        <h2 data-testid="company-name">{company.name}</h2>
        {company.is_fictional
          ? <Badge variant="info" label="가상회사" />
          : <Badge variant="alert" label="가상회사 표식 없음" />}
        <span className="cw-caption" data-testid="company-slug">{company.slug}</span>
      </div>
      <nav aria-label="회사 화면" className="cw-company-nav">
        <Link aria-current={screen === "pre-specs" ? "page" : undefined} to={`${base}/pre-specs`}>사전규격 목록</Link>
        <Link aria-current={screen === "profile" ? "page" : undefined} to={`${base}/profile`}>프로필</Link>
      </nav>
    </header>
  );
}

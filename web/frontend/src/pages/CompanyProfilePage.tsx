import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { Badge } from "../components/common/Badge";
import { EmptyState } from "../components/common/EmptyState";
import { CompanyHeader } from "../components/company/CompanyHeader";
import { KnowledgeGraph } from "../components/company/KnowledgeGraph";
import { describeCompanyApiError } from "../lib/apiErrors";
import {
  companyApi,
  companyFactStatusLabel,
  companyKeys,
  companyOriginLabel,
  isCompanyUuid,
  type CompanyProfileFact,
  type JsonValue,
  type Uuid,
} from "../lib/companyApi";
import "../styles/company-workspace.css";

/*
 * 회사 프로필 (`GET /api/companies/{company_id}/profile`, 공통 계약 §4).
 *
 * 회사 머리글과 프로필 identity(프로필·그래프·온톨로지 버전), 구조화 사실 목록을
 * 서버 값 그대로 보여 준다. 관계 목록·근거 패널(그래프 탐색)은 프로필이 읽힌 뒤
 * `components/company/KnowledgeGraph.tsx`가 그 프로필의 graph_version_id로 읽는다.
 * 프로필 편집은 범위 밖이다.
 *
 * 가상회사의 confirmed는 "시나리오 확정"이며 실제 회사 사실이 아니다. unknown은 값
 * 없이 미확인으로 남기고 0이나 "없음"으로 바꾸지 않는다.
 */
export function CompanyProfilePage() {
  const { companyId } = useParams();
  if (!isCompanyUuid(companyId)) {
    return (
      <section className="cw-page">
        <EmptyState
          tone="error"
          title="회사 주소가 올바르지 않습니다."
          description="주소의 회사 식별자를 확인할 수 없어 아무 회사의 프로필도 보여 주지 않습니다."
          action={{ label: "회사 다시 고르기", to: "/companies" }}
        />
      </section>
    );
  }
  return <CompanyProfile companyId={companyId} key={companyId} />;
}

function factValueText(fact: CompanyProfileFact): string {
  if (fact.status === "unknown" || fact.value === null) return "미확인";
  return jsonValueText(fact.value);
}

function jsonValueText(value: JsonValue): string {
  if (value === null) return "값 없음";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(jsonValueText).join(", ");
  return Object.entries(value)
    .map(([key, entry]) => `${key}: ${entry === null ? "미확인" : jsonValueText(entry)}`)
    .join(" · ");
}

function CompanyProfile({ companyId }: { companyId: Uuid }) {
  const profileQuery = useQuery({
    queryKey: companyKeys.profile(companyId, null),
    queryFn: ({ signal }) => companyApi.getProfile(companyId, null, { signal }),
    retry: false,
  });
  const profile = profileQuery.data;
  return (
    <section className="cw-page" aria-label="회사 프로필" data-company-id={companyId}>
      <CompanyHeader companyId={companyId} screen="profile" />
      {profileQuery.isPending ? (
        <p role="status">이 회사의 프로필을 불러오는 중입니다.</p>
      ) : profileQuery.isError ? (
        <EmptyState
          tone="error"
          title="이 회사의 프로필을 불러오지 못했습니다."
          problem={describeCompanyApiError(profileQuery.error, "회사 프로필을 불러오지 못했습니다.")}
          action={{ label: "다시 시도", onClick: () => { void profileQuery.refetch(); } }}
        />
      ) : profile ? (
        <>
          <div className="cw-section" aria-label="프로필 버전">
            <h3>프로필 버전</h3>
            <p className="cw-caption">
              가상회사 설정에서 만든 프로필입니다. "시나리오 확정"은 실제 회사 사실이 아닙니다.
            </p>
            <dl className="cw-facts">
              <dt>프로필</dt><dd className="cw-caption" data-testid="company-profile-version">{profile.profile_version_id}</dd>
              <dt>그래프</dt><dd className="cw-caption">{profile.graph_version_id}</dd>
              <dt>온톨로지</dt><dd className="cw-caption">{profile.ontology_version}</dd>
            </dl>
          </div>
          <div className="cw-section">
            <h3 id="company-profile-facts-title">구조화 사실</h3>
            {profile.facts.length === 0 ? (
              <p className="cw-caption">등록된 사실이 없습니다.</p>
            ) : (
              <table className="cw-table" aria-labelledby="company-profile-facts-title">
                <thead>
                  <tr>
                    <th className="cw-col-title" scope="col">항목</th>
                    <th scope="col">값</th>
                    <th scope="col">확실성</th>
                    <th scope="col">출처 구분</th>
                  </tr>
                </thead>
                <tbody>
                  {profile.facts.map((fact) => (
                    <tr data-fact-key={fact.fact_key} key={fact.fact_key}>
                      <td>{fact.label}</td>
                      <td>{factValueText(fact)}</td>
                      <td><Badge variant={fact.status === "unknown" ? "evidence-unknown" : fact.status === "inferred" ? "evidence-inferred" : "evidence-confirmed"} label={companyFactStatusLabel(fact.status)} /></td>
                      <td>{companyOriginLabel(fact.origin)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <KnowledgeGraph companyId={companyId} profile={profile} />
        </>
      ) : null}
    </section>
  );
}

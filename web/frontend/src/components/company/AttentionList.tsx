import type { CompanyProfileFact } from "../../lib/companyApi";
import {
  COMPANY_GROUP_LABEL,
  companyFactGroupOf,
  companyFactValueText,
  isDisplayedFact,
} from "../../lib/companyFacts";
import { CopyFactKeyButton, StatusPill, expiryNote } from "./FactGroupTable";
import "../../styles/company-ground-truth.css";

/*
 * "지금 확인하면 판정이 바뀌는 것 n"(ui-spec §4.6). 추정값(`proposed`)과 확인 필요(`unknown`)
 * 사실을 한 목록에 모은다 — 사이드바 건수(`company_attention`)와 같은 규칙이다.
 *
 * 읽기 전용이다. 행에는 항목·상태·내용과 항목 키 복사 버튼뿐이고 입력·저장·수정 버튼은 없다.
 * "영향 공고"는 판정 결과(RL-03)가 생기기 전까지 그리지 않는다(빈 열 금지).
 */

interface AttentionListProps {
  facts: readonly CompanyProfileFact[];
  today: string;
  warningDays: number;
}

function attentionSub(fact: CompanyProfileFact): string {
  const group = companyFactGroupOf(fact.fact_key);
  const groupLabel = group ? COMPANY_GROUP_LABEL[group] : "회사 정보";
  return `${groupLabel} · ${fact.status === "proposed" ? "제안값, 사람 확인 전" : "값 미입력"}`;
}

export function AttentionList({ facts, today, warningDays }: AttentionListProps) {
  return (
    <section aria-labelledby="co-attention-title" className="co-attention" data-testid="company-attention">
      <h2 className="co-block-title" id="co-attention-title">
        지금 확인하면 판정이 바뀌는 것
        <span className="co-block-count" data-testid="company-attention-count">{facts.length}</span>
      </h2>
      {facts.length === 0 ? (
        <p className="co-empty" role="status">지금 확인이 필요한 항목이 없습니다.</p>
      ) : (
        <ul aria-labelledby="co-attention-title" className="co-attention-list">
          {facts.filter(isDisplayedFact).map((fact) => {
            const expiry = expiryNote(fact, today, warningDays);
            return (
              <li className="co-attention-row" data-fact-key={fact.fact_key} data-fact-status={fact.status} key={fact.fact_key}>
                <span className="co-attention-main">
                  <span className="co-row-title">{fact.label}</span>
                  <span className="co-row-sub">{attentionSub(fact)}</span>
                </span>
                <StatusPill status={fact.status} />
                <span className="co-attention-value">
                  <span className={fact.status === "unknown" ? "co-value is-empty" : "co-value"}>{companyFactValueText(fact)}</span>
                  {expiry ? <span className="co-row-sub is-warning">{expiry}</span> : null}
                </span>
                <CopyFactKeyButton fact={fact} />
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

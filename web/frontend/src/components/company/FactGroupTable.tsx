import { useEffect, useRef, useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { companyOriginLabel, type CompanyProfileFact } from "../../lib/companyApi";
import {
  COMPANY_STATUS_LABEL,
  companyFactValueText,
  daysUntilExpiry,
  isDisplayedFact,
  validUntilOf,
  type CompanyDisplayStatus,
} from "../../lib/companyFacts";
import "../../styles/company-ground-truth.css";

/*
 * `/company`의 공통 조각(ui-spec §3 상태 pill·표 규칙, RL-00 spec 읽기 전용 결정).
 *
 * - 상태 pill은 확인됨(success)·추정값(blue)·확인 필요(warning) 셋이다. 글자는 항상
 *   상태 이름이고 색은 테마 토큰만 읽는다(`styles/company-ground-truth.css`).
 *   `inferred`는 이 화면에 그리지 않는다.
 * - 행동 버튼(맞음·수정·입력)은 없다. 값은 회사 파일을 고쳐 다시 등록한다. 각 행에는
 *   항목 키를 복사하는 ghost 버튼 하나만 있다.
 */

export function StatusPill({ status }: { status: CompanyDisplayStatus }) {
  return (
    <span className={`co-pill is-${status}`} data-status={status}>
      {COMPANY_STATUS_LABEL[status]}
    </span>
  );
}

/** 출처 보조 줄. 확인 필요(unknown)는 출처가 없으므로 적지 않는다. */
export function factOriginNote(fact: CompanyProfileFact): string | null {
  return fact.status === "unknown" ? null : companyOriginLabel(fact.origin);
}

type CopyState = "idle" | "copied" | "failed";

async function writeClipboard(text: string): Promise<void> {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  // 사내망 http 접속은 보안 컨텍스트가 아니라 Clipboard API가 없다. 선택 복사로 대신한다.
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.className = "co-clipboard-sink";
  document.body.appendChild(area);
  area.select();
  const copied = document.execCommand("copy");
  area.remove();
  if (!copied) throw new Error("copy_failed");
}

/** 항목 키(`fact_key`)를 클립보드로 복사한다. 키 자체는 화면에 글자로 적지 않는다. */
export function CopyFactKeyButton({ fact }: { fact: CompanyProfileFact }) {
  const [state, setState] = useState<CopyState>("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);
  const copy = async () => {
    let next: CopyState = "copied";
    try {
      await writeClipboard(fact.fact_key);
    } catch {
      next = "failed";
    }
    setState(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 2_000);
  };
  const visible = state === "copied" ? "복사됨" : state === "failed" ? "복사 실패" : "키 복사";
  return (
    <span className="co-copy">
      <Button label={`${fact.label} 항목 키 복사`} onClick={() => { void copy(); }} size="sm" variant="ghost">
        {visible}
      </Button>
      {state !== "idle" ? (
        <span className="visually-hidden" role="status">
          {state === "copied" ? `${fact.label} 항목 키를 복사했습니다.` : `${fact.label} 항목 키를 복사하지 못했습니다.`}
        </span>
      ) : null}
    </span>
  );
}

/** 값 칸 아래 보조 줄에 놓는 유효기간 안내. 자격의 `valid_until`이 있을 때만 있다. */
export function expiryNote(fact: CompanyProfileFact, today: string, warningDays: number): string | null {
  const days = daysUntilExpiry(fact, today);
  const until = validUntilOf(fact);
  if (days === null || until === null || days > warningDays) return null;
  return days < 0 ? `만료됨 · ${until}` : days === 0 ? `오늘 만료 · ${until}` : `${days}일 후 만료 · ${until}`;
}

interface FactGroupTableProps {
  caption: string;
  facts: readonly CompanyProfileFact[];
  today: string;
  warningDays: number;
}

/** 그룹 표 4열: 항목 · 상태 · 내용 · 항목 키 복사. 영향 공고 열은 판정 결과(RL-03) 전까지 없다. */
export function FactGroupTable({ caption, facts, today, warningDays }: FactGroupTableProps) {
  const rows = facts.filter(isDisplayedFact);
  if (rows.length === 0) {
    return <p className="co-empty" role="status">이 항목에 등록된 값이 없습니다.</p>;
  }
  return (
    <table className="co-table">
      <caption className="visually-hidden">{caption}</caption>
      <thead>
        <tr>
          <th className="co-col-label" scope="col">항목</th>
          <th className="co-col-status" scope="col">상태</th>
          <th scope="col">내용</th>
          <th className="co-col-action" scope="col"><span className="visually-hidden">항목 키 복사</span></th>
        </tr>
      </thead>
      <tbody>
        {rows.map((fact) => {
          const origin = factOriginNote(fact);
          const expiry = expiryNote(fact, today, warningDays);
          return (
            <tr data-fact-key={fact.fact_key} data-fact-status={fact.status} key={fact.fact_key}>
              <th scope="row">
                <span className="co-row-title">{fact.label}</span>
                {origin ? <span className="co-row-sub">{origin}</span> : null}
              </th>
              <td><StatusPill status={fact.status} /></td>
              <td>
                <span className={fact.status === "unknown" ? "co-value is-empty" : "co-value"}>{companyFactValueText(fact)}</span>
                {expiry ? <span className="co-row-sub is-warning">{expiry}</span> : null}
              </td>
              <td className="co-col-action"><CopyFactKeyButton fact={fact} /></td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

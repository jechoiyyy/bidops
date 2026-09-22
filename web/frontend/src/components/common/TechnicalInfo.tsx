import type { ReactNode } from "react";
import "../../styles/technical-info.css";

/**
 * 접힌 `기술 정보`(ADR-0065 결정 1 `이동`·결정 2).
 *
 * 식별자·해시·오류 코드·정책 버전은 운영 화면에 받을 자리가 없으므로 지우지
 * 않고 같은 화면의 접힌 곳으로 모은다. **값 자체는 줄이지 않는다** — 8자
 * 축약이나 말줄임을 만들지 않고 전문을 줄바꿈해 보인다.
 *
 * 심층 검토 보고서가 먼저 쓰던 부품이고(`components/deep-review/`), 최종
 * Go/No-Go·입찰 변경 비교·공고 정정·폼 오류도 같은 접힘을 쓰게 되어 공용으로
 * 옮겼다(R6). 클래스 이름(`deep-review-technical*`)은 그대로 두었다 — 동작과
 * 화면 검사가 가리키는 자리를 바꾸지 않기 위해서다.
 *
 * 접힘은 native `<details>`/`<summary>`다. 이 저장소에서 같은 성격의 기술
 * 세부는 `<details>`로 접혀 있고(`bid-delta-technical-details`), Astryx
 * `Collapsible`은 절 머리 크기의 trigger를 그리는 구역 단위 접힘에 쓰인다
 * (사전규격 상세 ⑥). 여기는 카드 안의 작은 접힘이고 안에 든 것이 정적인
 * 문자열뿐이라 native 쪽을 따른다 — 키보드 조작·접근 이름·기본 접힘이
 * 브라우저 기본값으로 따라온다.
 */
export function TechnicalInfo({
  children,
  className,
  summary,
}: {
  children: ReactNode;
  className?: string;
  /** 접힘의 접근 이름. 한 화면에 여럿이므로 무엇의 기술 정보인지 붙인다. */
  summary: string;
}) {
  return (
    <details className={`deep-review-technical${className ? ` ${className}` : ""}`}>
      <summary>{summary}</summary>
      <div className="deep-review-technical-body">{children}</div>
    </details>
  );
}

export interface TechnicalFact {
  label: string;
  /** 없으면 `값 없음`을 그대로 적는다. 0·미확인과 섞지 않는다. */
  value: string;
}

/** 접힌 곳 안의 라벨·값 목록. 값은 잘리지 않고 줄바꿈으로 흐른다. */
export function TechnicalFacts({ facts, label }: { facts: TechnicalFact[]; label: string }) {
  return (
    <dl aria-label={label} className="deep-review-technical-facts">
      {facts.map((fact) => (
        <div key={fact.label}>
          <dt>{fact.label}</dt>
          <dd className="mono">{fact.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export default TechnicalInfo;

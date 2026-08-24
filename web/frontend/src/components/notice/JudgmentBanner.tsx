import type { JudgmentResponse } from "../../lib/types";
import { formatNumber, present } from "../../lib/format";
import { gradeRailClass } from "../../lib/grade";

interface JudgmentBannerProps {
  judgment: JudgmentResponse | null;
}

// 관점 평가는 자유 문자열이므로 우호 여부를 문구로 가려낸다.
// 계약이 값을 열거하지 않기 때문에, 판정하기 어려운 값은 세지 않고 남겨 둔다.
const FAVOURABLE = ["우호", "적합", "충족", "유리"];

function favourableCount(judgment: JudgmentResponse | null): number {
  return (judgment?.perspectives ?? []).filter((perspective) => {
    const assessment = perspective.assessment?.trim();
    return Boolean(assessment) && FAVOURABLE.some((token) => assessment!.includes(token));
  }).length;
}

/**
 * 판정 결과에서 담당자가 가장 먼저 봐야 하는 값만 모아 상세 화면 맨 위에 놓는다.
 * 등급과 종합 권고, 다음 행동, 확인해야 할 항목 수를 한 시선에 담는 것이 목적이다.
 */
export function JudgmentBanner({ judgment }: JudgmentBannerProps) {
  const perspectives = judgment?.perspectives ?? [];
  const verificationItems = judgment?.verification_items ?? [];
  const blockingCount = verificationItems.filter((item) => item.blocking).length;
  const counterCount = judgment?.counterarguments.length ?? 0;
  const favourable = favourableCount(judgment);

  return (
    <section className={`judgment-banner ${gradeRailClass(judgment?.grade ?? null)}`} aria-label="판정 요약">
      <div className="judgment-banner-grade">
        <span className="judgment-banner-eyebrow">판정 등급</span>
        <strong>{present(judgment?.grade, "등급 미확인")}</strong>
        <span className="judgment-banner-perspective mono tabular-nums">
          {perspectives.length > 0 ? `관점 ${formatNumber(perspectives.length)}개 중 ${formatNumber(favourable)}개 우호` : "관점 평가 없음"}
        </span>
      </div>

      <div className="judgment-banner-main">
        <p className="judgment-banner-summary">{judgment?.summary?.trim() || "종합 권고가 없습니다."}</p>
        <div className="judgment-banner-next">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M5 12h13M13 6l6 6-6 6" />
          </svg>
          <span>다음 행동</span>
          <strong>{judgment?.next_action?.trim() || "다음 행동 미확인"}</strong>
        </div>
      </div>

      <dl className="judgment-banner-counts">
        <div>
          <dt>확인 항목</dt>
          <dd className="mono tabular-nums">{formatNumber(verificationItems.length)}</dd>
        </div>
        <div className={blockingCount > 0 ? "is-blocking" : ""}>
          <dt>차단 항목</dt>
          <dd className="mono tabular-nums">{formatNumber(blockingCount)}</dd>
        </div>
        <div>
          <dt>반론</dt>
          <dd className="mono tabular-nums">{formatNumber(counterCount)}</dd>
        </div>
      </dl>
    </section>
  );
}

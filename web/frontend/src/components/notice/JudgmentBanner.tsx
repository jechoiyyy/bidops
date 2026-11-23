import type { JudgmentResponse } from "../../lib/types";
import { SideFacts } from "../common/Facts";
import { formatNumber } from "../../lib/format";
import { TERM_SENSE } from "../../lib/glossary";

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
    <SideFacts items={[
      { label: "종합 권고", value: judgment?.summary?.trim() || "종합 권고가 없어요." },
      { label: TERM_SENSE.nextActionGuide, value: judgment?.next_action?.trim() || `${TERM_SENSE.nextActionGuide} 미확인` },
      { label: "관점 평가", value: perspectives.length > 0 ? `관점 ${formatNumber(perspectives.length)}개 중 ${formatNumber(favourable)}개 우호` : "관점 평가 없음" },
      { label: "확인 항목", value: formatNumber(verificationItems.length) },
      { label: "차단 항목", value: formatNumber(blockingCount) },
      { label: "반론", value: formatNumber(counterCount) },
    ]} />
  );
}

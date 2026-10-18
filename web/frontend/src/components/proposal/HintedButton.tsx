import { useId } from "react";
import { Button } from "@astryxdesign/core/Button";

/*
 * 비활성 이유를 title(마우스)과 숨은 설명(낭독기) 둘 다로 주는 버튼. 레코드 헤더의 `rec-action-hint`
 * 패턴과 같다. 이유가 `null`이면 평범한 버튼이다.
 */

interface HintedButtonProps {
  label: string;
  onClick: () => void;
  /** 비활성이면 그 이유. 열 수 있으면 `null`이다. */
  blockedReason: string | null;
  variant?: "primary" | "secondary";
  pendingLabel?: string | null;
}

export function HintedButton({ label, onClick, blockedReason, variant = "secondary", pendingLabel = null }: HintedButtonProps) {
  const hintId = useId();
  return (
    <span className="rec-action-hint" title={blockedReason ?? undefined}>
      <Button
        aria-describedby={blockedReason ? hintId : undefined}
        isDisabled={blockedReason !== null}
        label={pendingLabel ?? label}
        onClick={onClick}
        size="sm"
        variant={variant}
      />
      {blockedReason ? <span className="visually-hidden" id={hintId}>{blockedReason}</span> : null}
    </span>
  );
}

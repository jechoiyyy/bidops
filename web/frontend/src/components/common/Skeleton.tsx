import "../../styles/skeleton.css";

/**
 * 로딩 골격.
 *
 * 상세 화면은 쿼리 넷·다섯이 각자 "…불러오는 중입니다" 문장을 뿌렸고, 그 문장
 * 들이 서로 다른 자리에서 뜨고 사라지며 레이아웃을 흔들었다. 골격은 자리를
 * 미리 잡아 그 흔들림을 없애고, 낭독기에는 문장 하나만 남긴다.
 *
 * `styles/detail-skeleton.css`의 `detail-skeleton`은 이름이 비슷하지만 로딩이
 * 아니라 상세 3종이 공유하는 **레이아웃 골격**이다. 여기의 skeleton은 로딩
 * 자리표시자이며 둘을 섞지 않는다.
 *
 * - 색은 테마 토큰만 읽는다(ADR-0048).
 * - `prefers-reduced-motion`이면 애니메이션이 없다(`styles/skeleton.css`).
 * - 낭독기에는 `role="status"`와 숨김 문장 하나로 알린다. 문장은 화면마다 달라
 *   같은 이름의 live region이 여럿 생겨도 서로 구분된다.
 */

interface SkeletonBlockProps {
  /** 그릴 줄 수. 실제 내용의 줄 수와 비슷하게 준다. */
  lines?: number;
  /** 줄 높이. `text`는 본문 한 줄, `title`은 제목 한 줄, `block`은 문단 덩어리. */
  height?: "text" | "title" | "block";
  /**
   * 낭독기에 읽힐 문장. 화면마다 무엇을 기다리는지 다르게 적는다.
   * 옆의 문구가 이미 같은 사실을 말하고 있으면 `null`을 줘서 live region을
   * 겹치지 않게 한다 — 같은 문장을 여러 번 읽는 것은 도움이 아니다.
   */
  label: string | null;
  className?: string;
}

export function SkeletonBlock({ lines = 3, height = "text", label, className = "" }: SkeletonBlockProps) {
  const rows = Math.max(1, Math.trunc(lines));
  const silent = label === null;
  return (
    <div
      className={`skeleton skeleton-${height} ${className}`.trim()}
      role={silent ? undefined : "status"}
      aria-live={silent ? undefined : "polite"}
      aria-hidden={silent ? "true" : undefined}
    >
      {/* 낭독기에는 문장 하나만 남기고 화면에서는 감춘다.
          `visually-hidden`은 `styles/theme.css`가 이미 갖고 있는 유틸이다. */}
      {silent ? null : <span className="visually-hidden">{label}</span>}
      {Array.from({ length: rows }, (_, index) => (
        <span aria-hidden="true" className="skeleton-line" data-skeleton-line={index} key={index} />
      ))}
    </div>
  );
}

interface SkeletonPanelProps {
  /** 제목 줄을 그릴지 여부. 제목이 이미 있는 패널 안에서는 끈다. */
  withTitle?: boolean;
  lines?: number;
  label: string;
  className?: string;
}

/** Panel 골격 하나. 패널 테두리와 여백까지 미리 잡아 자리를 흔들지 않는다. */
export function SkeletonPanel({ withTitle = true, lines = 3, label, className = "" }: SkeletonPanelProps) {
  return (
    <div className={`skeleton-panel ${className}`.trim()}>
      {withTitle ? <span aria-hidden="true" className="skeleton-line skeleton-panel-title" /> : null}
      <SkeletonBlock label={label} lines={lines} />
    </div>
  );
}

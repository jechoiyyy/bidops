import type { AnchorHTMLAttributes, ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Heading } from "@astryxdesign/core/Heading";
import { Text } from "@astryxdesign/core/Text";
import { StatusMark } from "../common/Marks";

export function Small({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <Text as="span" className={`dash-small ${className}`} color="secondary">{children}</Text>;
}

export function Tag({ label, tone = "neutral" }: { label: string; tone?: "neutral" | "error" | "success" | "warning" }) {
  return <StatusMark mark={{ label, tone: tone === "success" ? "confirmed" : tone }} />;
}

function RouterAnchor({ href = "", ...props }: AnchorHTMLAttributes<HTMLAnchorElement>) {
  return <Link {...props} to={href} />;
}

export function LinkButton({ to, label, icon, secondary = false }: { to: string; label: string; icon?: ReactNode; secondary?: boolean }) {
  return <Button as={RouterAnchor} href={to} label={label} icon={icon} size="sm" variant={secondary ? "secondary" : "ghost"} />;
}

/** 화면의 큰 묶음. 묶음 제목이 h2다. */
export function DashboardBlock({ id, title, caption, actions, children }: {
  id: string; title: string; caption?: ReactNode; actions?: ReactNode; children: ReactNode;
}) {
  const headingId = `dash-block-${id}`;
  return <section className="dash-block" aria-labelledby={headingId} data-block={id}>
    <header className="dash-block-head">
      <Heading level={2} id={headingId}>{title}</Heading>
      {caption && <Small>{caption}</Small>}
      {actions && <div className="dash-block-actions">{actions}</div>}
    </header>
    {children}
  </section>;
}

/** 칸 안의 건수 링크 하나. `to`의 목록 기본 보기가 정확히 이 건수를 보인다. */
export interface DashCount {
  key: string;
  label: string;
  /** `N건`·`확인 중`·`미확인`. 0은 0건으로 적는다. */
  value: string;
  to: string;
}

/**
 * 맨 위 요약 줄의 한 칸: 첫 줄은 칸 이름과 큰 건수 링크(없으면 보조 건수 링크들), 둘째 줄은 설명과
 * 보조 건수 링크. 보조 건수는 다른 목록의 건수이므로 큰 건수에 더하지 않는다.
 */
export function SummaryCell({ id, title, main, basis, extras = [], hot = false }: {
  id: string; title: string; main?: DashCount; basis?: string; extras?: DashCount[]; hot?: boolean;
}) {
  const extraLinks = extras.map(extra => <Link className="dash-summary-extra" data-count={extra.key} key={extra.key} to={extra.to}>{`${extra.label} ${extra.value}`}</Link>);
  return <section className={hot ? "dash-summary-cell is-hot" : "dash-summary-cell"} data-summary={id} aria-label={title}>
    <div className="dash-summary-lead">
      <Text className="dash-summary-title" weight="semibold">{title}</Text>
      {main ? <Link className="dash-summary-main" data-count={main.key} to={main.to} aria-label={`${main.label} ${main.value}`}>{main.value}</Link> : extraLinks}
    </div>
    <div className="dash-summary-aside">
      {basis ? <Small>{basis}</Small> : null}
      {main ? extraLinks : null}
    </div>
  </section>;
}

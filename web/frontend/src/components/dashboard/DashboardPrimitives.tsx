import type { AnchorHTMLAttributes, ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@astryxdesign/core/Button";
import { Heading } from "@astryxdesign/core/Heading";
import { Text } from "@astryxdesign/core/Text";
import { Token } from "@astryxdesign/core/Token";
import { CircleAlert, LoaderCircle, Search } from "lucide-react";

export function Small({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <Text as="span" className={`dash-small ${className}`} color="secondary">{children}</Text>;
}

export function Tag({ label, tone = "neutral" }: { label: string; tone?: "neutral" | "error" | "success" | "warning" }) {
  return <Token label={label} color={tone === "error" ? "red" : tone === "success" ? "green" : tone === "warning" ? "orange" : "gray"} size="sm" />;
}

function RouterAnchor({ href = "", ...props }: AnchorHTMLAttributes<HTMLAnchorElement>) {
  return <Link {...props} to={href} />;
}

export function LinkButton({ to, label, icon, secondary = false }: { to: string; label: string; icon?: ReactNode; secondary?: boolean }) {
  return <Button as={RouterAnchor} href={to} label={label} icon={icon} size="sm" variant={secondary ? "secondary" : "ghost"} />;
}

/**
 * 대시보드의 큰 묶음(설계고도화안 C-8): 오늘 결정할 것 · 확인할 것 · 새로 볼 것. 묶음 제목이 h2이고
 * 안의 업무 패널 제목은 h3이다.
 */
export function DashboardBlock({ id, title, caption, children }: { id: string; title: string; caption: ReactNode; children: ReactNode }) {
  const headingId = `dash-block-${id}`;
  return <section className="dash-block" aria-labelledby={headingId} data-block={id}>
    <header className="dash-block-head"><Heading level={2} id={headingId}>{title}</Heading><Small>{caption}</Small></header>
    {children}
  </section>;
}

/** 묶음 머리의 건수 한 칸. `to`가 있으면 그 목록의 기본 보기가 정확히 이 건수를 보인다. */
export interface DashCount {
  key: string;
  label: string;
  /** `N건`·`확인 중`·`미확인`·`집계 없음`. 0은 0건으로 적는다. */
  value: string;
  basis: string;
  to: string | null;
}

export function CountStrip({ label, items }: { label: string; items: readonly DashCount[] }) {
  return <ul className="dash-count-strip" aria-label={label}>
    {items.map((item) => {
      const body = <>
        <Small className="dash-count-label">{item.label}</Small>
        <Text className="dash-count-value" weight="semibold">{item.value}</Text>
        <Small>{item.basis}</Small>
      </>;
      return <li className="dash-count-item" data-count={item.key} key={item.key}>
        {item.to ? <Link className="dash-count-cell" to={item.to}>{body}</Link> : <div className="dash-count-cell is-static">{body}</div>}
      </li>;
    })}
  </ul>;
}

export function DashboardPanel({ title, caption, action, className = "", children, footer }: {
  title: string; caption?: ReactNode; action?: ReactNode; className?: string; children: ReactNode; footer?: ReactNode;
}) {
  const heading = <Heading level={3}>{title}</Heading>;
  return <section className={`dash-panel ${className}`} aria-label={title}>
    <header className="dash-panel-head">{caption ? <div className="dash-panel-title">{heading}<Small>{caption}</Small></div> : heading}{action}</header>
    <div className="dash-panel-body">{children}</div>
    {footer && <footer className="dash-panel-foot">{footer}</footer>}
  </section>;
}

export function DashboardState({ kind, title, children, action, inline = false }: {
  kind: "empty" | "loading" | "error"; title: string; children?: ReactNode; action?: ReactNode; inline?: boolean;
}) {
  const Icon = kind === "error" ? CircleAlert : kind === "loading" ? LoaderCircle : Search;
  return <div className={inline ? "dash-empty-inline" : "dash-run-state"} role={kind === "error" ? "alert" : "status"}>
    <Icon aria-hidden="true" />
    {inline ? <Text>{title}</Text> : <Heading level={2}>{title}</Heading>}
    {children && <Small>{children}</Small>}{action}
  </div>;
}

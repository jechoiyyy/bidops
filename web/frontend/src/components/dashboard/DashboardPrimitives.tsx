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

export function DashboardPanel({ title, caption, action, className = "", children, footer }: {
  title: string; caption?: ReactNode; action?: ReactNode; className?: string; children: ReactNode; footer?: ReactNode;
}) {
  const heading = <Heading level={2}>{title}</Heading>;
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

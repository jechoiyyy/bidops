/*
 * 공용 부품(T-계열). 모든 화면 틀이 이 파일의 부품만 써서 상태·마감·사실·결정 띠를 그린다.
 * 같은 기능이 화면마다 다르게 그려지는 일을 막는 것이 목적이므로, 화면 파일은 여기 없는 모양을 새로 만들지 않는다.
 */
import { createContext, useContext, type CSSProperties, type ReactNode } from "react";
import { Check, CircleDot, Minus } from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Kbd } from "@astryxdesign/core/Kbd";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { Step, Stepper } from "@astryxdesign/core/Stepper";
import { Heading, Text } from "@astryxdesign/core/Text";
import { Token, type TokenColor } from "@astryxdesign/core/Token";

export type Variant = "k" | "a" | "b" | "c";
export const VariantContext = createContext<Variant>("k");
export const useVariant = () => useContext(VariantContext);

/**
 * 보기 방안 — 2026-11-23 시안 1(표 작업대)을 기준으로 정한 뒤, 실무자가 보기 편하게 만드는 세 가지 방법.
 * base=시안 1 그대로, x=크게 보기, y=훑기 길잡이, z=내 화면 맞춤(사용자가 고르는 보기 설정).
 */
export type Mode = "base" | "x" | "y" | "z";
export interface ViewPrefs { density: "compact" | "balanced" | "spacious"; text: "normal" | "large"; columns: string[]; inspector: boolean }
export const OPTIONAL_COLUMNS = [{ value: "agency", label: "발주기관" }, { value: "budget", label: "예산" }, { value: "mark", label: "상태" }, { value: "deadline", label: "마감" }];
export const DEFAULT_PREFS: ViewPrefs = { density: "compact", text: "normal", columns: OPTIONAL_COLUMNS.map((column) => column.value), inspector: true };
export interface ModeState { mode: Mode; prefs: ViewPrefs; setPrefs: (patch: Partial<ViewPrefs>) => void }
export const ModeContext = createContext<ModeState>({ mode: "base", prefs: DEFAULT_PREFS, setPrefs: () => undefined });
export const useMode = () => useContext(ModeContext);

/** accent = 추적 중, warning = 결정·사람 확인 필요, info = 모델 판단, success·neutral = 완료·정상·미선택·미확인. */
export type Tone = "success" | "warning" | "error" | "accent" | "info" | "neutral";
export interface Mark { label: string; tone: Tone }
export interface Fact { label: string; value: ReactNode; strong?: boolean }
export interface Deadline { text: string; level: "urgent" | "soon" | "normal" | "none" }
/** done=확정, current=지금 단계, unknown=미확인(완료로 그리지 않는다), todo=아직 오지 않음. */
export interface FlowStep { label: string; description?: string; status?: "success" | "warning" | "error" | "accent"; state?: "done" | "current" | "unknown" | "todo" }
export interface Action { label: string; kind?: "primary" | "secondary" | "ghost" | "destructive"; disabled?: boolean }
export interface Decision {
  stateLabel: string;
  state: Mark;
  note?: string;
  hint?: string;
  actions: Action[];
}
export interface Shortcut { keys: string; label: string }
export interface SectionModel { id: string; title: string; aside?: ReactNode; body: ReactNode }

/**
 * 상태 표식 채움색 — 운영 셸의 상태 칩(`.bo-tag`, shell-relaxed.css)과 같은 토큰 짝이며 새 색을 만들지 않는다
 * (ADR-0076 결정 7). 추적 중 = 브랜드 옅은 채움, 결정 필요·사람 검토 필요 = 주의색, 모델 판단 = 정보색(보라),
 * 완료·정상·운영 활성·미선택·미확인 = 회색(운영의 Token 기본 채움). 참조 실행·표식 없음은 neutral이라 성공·실패 색이 아니다.
 * Token의 color 클래스가 특이성을 높여 두어 운영 칩의 짝은 style로 넘긴다. StatusDot은 테마 빌드가 Astryx 기본
 * 파랑·노랑·초록 hex를 그대로 내보내므로 쓰지 않는다.
 */
const TONE_FILL: Record<Tone, { color: TokenColor; style?: CSSProperties }> = {
  accent: { color: "default", style: { backgroundColor: "var(--color-accent-muted)", color: "var(--color-success)" } },
  warning: { color: "default", style: { backgroundColor: "var(--color-warning-muted)", color: "var(--color-warning)" } },
  error: { color: "default", style: { backgroundColor: "var(--color-error-muted)", color: "var(--color-error)" } },
  info: { color: "purple" },
  success: { color: "default" },
  neutral: { color: "default" },
};

/** T8 상태 표식 — 채움 표식. 글자가 항상 상태 이름이라 색만으로 뜻을 전하지 않는다. */
export function StatusMark({ mark }: { mark: Mark }) {
  const fill = TONE_FILL[mark.tone];
  return <Token className="mk-mark" data-tone={mark.tone} size="sm" color={fill.color} style={fill.style} label={mark.label} />;
}

/** T8 분류 표식 — 업무구분·발견 경로처럼 상태가 아닌 분류에만 쓴다. 운영과 같은 Token 기본 채움. */
export function Tag({ label }: { label: string }) {
  return <Token size="sm" color="default" label={label} />;
}

/** T8 마감 — 표식이 아니라 글자. 임박 정도는 굵기와 색을 같이 쓴다. */
export function DeadlineText({ deadline }: { deadline: Deadline }) {
  const { mode } = useMode();
  const [main, sub] = deadline.text.split(" · ");
  // 훑기 길잡이: 남은 날(D-2)을 먼저 굵게, 날짜는 뒤에 옅게 둔다.
  if (mode === "y" && sub) {
    return <span className="mk-deadline" data-level={deadline.level} data-split="true"><strong>{main}</strong><span>{sub}</span></span>;
  }
  return <span className="mk-deadline" data-level={deadline.level}>{deadline.text}</span>;
}

/** T9 핵심 수치 — 판단에 먼저 필요한 값(마감·금액)을 큰 글자로 한 줄에 둔다. 훑기 길잡이에서만 쓴다. */
export function KeyFigures({ facts }: { facts: Fact[] }) {
  if (facts.length === 0) return null;
  return (
    <div className="mk-keys">
      {facts.map((fact) => (
        <div className="mk-key" key={fact.label}>
          <Text type="supporting" color="secondary" display="block">{fact.label}</Text>
          <span className="mk-key-value">{fact.value}</span>
        </div>
      ))}
    </div>
  );
}

/** T9 사실 목록 — 라벨·값 쌍은 언제나 MetadataList 하나로 그린다. */
export function Facts({ facts, columns = 2, side = false }: { facts: Fact[]; columns?: number; side?: boolean }) {
  return (
    <div className="mk-facts" data-side={side ? "true" : "false"}>
      <MetadataList columns={side ? "single" : columns} label={side ? { position: "start", width: 108 } : { position: "top" }}>
        {facts.map((fact) => (
          <MetadataListItem key={fact.label} label={fact.label}>
            <span className={fact.strong ? "mk-fact-strong" : "mk-fact-value"}>{fact.value}</span>
          </MetadataListItem>
        ))}
      </MetadataList>
    </div>
  );
}

/**
 * T12 사업 흐름·단계 진행.
 * Stepper는 activeStep 앞의 단계를 모두 완료로 그린다. 앞 단계에 미확인이 섞이면(연결을 확인하지 못한 발주계획 등)
 * 완료 체크가 거짓이 되므로, 그때는 진행 위치를 쓰지 않고 단계마다 표시를 직접 정한다.
 */
export function Flow({ steps, active, vertical = false }: { steps: FlowStep[]; active: number; vertical?: boolean }) {
  const activeState = steps[active]?.state;
  const linear = (activeState === undefined || activeState === "current")
    && steps.every((step, index) => index >= active || step.state === undefined || step.state === "done");
  return (
    <div className="mk-flow">
      <Stepper activeStep={linear ? active : -1} orientation={vertical ? "vertical" : "horizontal"} density="compact" label="사업 흐름">
        {steps.map((step, index) => {
          const state = step.state ?? (index < active ? "done" : index === active ? "current" : "todo");
          const indicator = linear ? "auto" : state === "done" ? <Check aria-hidden="true" /> : state === "current" ? <CircleDot aria-hidden="true" /> : state === "unknown" ? <Minus aria-hidden="true" /> : "number";
          const status = step.status ?? (linear ? undefined : state === "done" ? "success" : state === "current" ? "accent" : undefined);
          return <Step key={step.label} step={index} label={step.label} description={step.description} status={status} indicator={indicator} />;
        })}
      </Stepper>
    </div>
  );
}

/** T10 구역 — 제목 한 줄 + 오른쪽 보조 + 본문. 카드·테두리 상자를 두지 않는다. */
export function SectionBlock({ section }: { section: SectionModel }) {
  return (
    <section className="mk-section" id={section.id}>
      <div className="mk-section-head">
        <Heading level={3}>{section.title}</Heading>
        {section.aside ? <span className="mk-section-aside">{section.aside}</span> : null}
      </div>
      <div className="mk-section-body">{section.body}</div>
    </section>
  );
}

/** T10 채움 블록 — 모델 근거·안내처럼 본문과 구분할 내용. 테두리 대신 fill. */
export function FillBlock({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="mk-fill">
      {title ? <Text type="label" weight="semibold" display="block">{title}</Text> : null}
      <div className="mk-fill-body">{children}</div>
    </div>
  );
}

export function Para({ children, dim = false }: { children: ReactNode; dim?: boolean }) {
  return <Text type="body" as="p" display="block" color={dim ? "secondary" : "primary"}>{children}</Text>;
}

/** T10 빈 상태 — 주 버튼은 다른 화면과 같은 primary 하나. */
export function Empty({ title, description, action }: { title: string; description?: string; action?: string }) {
  return (
    <div className="mk-empty">
      <EmptyState
        title={title}
        description={description}
        isCompact
        actions={action ? <Button label={action} variant="primary" /> : undefined}
      />
    </div>
  );
}

/** T7 결정 띠 — 왼쪽은 현재 상태, 오른쪽은 보조 행동 다음에 주 행동 하나. 네 목록·두 상세가 같은 순서를 쓴다. */
export function DecisionBar({ decision, readingWidth = false }: { decision: Decision; readingWidth?: boolean | "outline" }) {
  return (
    <div className="mk-decision" role="region" aria-label="결정 영역" data-reading={readingWidth === "outline" ? "outline" : readingWidth ? "true" : "false"}>
      <div className="mk-decision-inner">
        <div className="mk-decision-state">
          <Text type="supporting" color="secondary">{decision.stateLabel}</Text>
          <StatusMark mark={decision.state} />
          {decision.note ? <Text type="supporting" color="secondary">{decision.note}</Text> : null}
        </div>
        <div className="mk-decision-actions">
          {decision.hint ? <Text type="supporting" color="secondary">{decision.hint}</Text> : null}
          {decision.actions.map((action) => (
            <Button key={action.label} label={action.label} variant={action.kind ?? "secondary"} isDisabled={action.disabled} />
          ))}
        </div>
      </div>
    </div>
  );
}

/** T10 주장 목록 — 개요·근거 문장마다 원문 쪽 링크를 오른쪽에 붙인다. */
export function Claims({ items }: { items: { text: string; page?: string }[] }) {
  return (
    <ul className="mk-claims">
      {items.map((item) => (
        <li key={item.text}>
          <span>{item.text}</span>
          {item.page ? <a className="mk-link" href="#">{item.page}</a> : null}
        </li>
      ))}
    </ul>
  );
}

/** T10 바로가기 목록 — 다른 화면으로 가는 링크 묶음. */
export function Links({ items }: { items: string[] }) {
  return <ul className="mk-links">{items.map((item) => <li key={item}><a className="mk-link" href="#">{item} →</a></li>)}</ul>;
}

/** T5 단축키 안내 — 목록 아래 한 줄. 화면마다 문구가 달라지지 않게 부품으로 둔다. */
export function Shortcuts({ items }: { items: Shortcut[] }) {
  return (
    <span className="mk-shortcuts">
      {items.map((item) => (
        <span className="mk-shortcut" key={item.keys}><Kbd keys={item.keys} />{item.label ? <Text type="supporting" color="secondary">{item.label}</Text> : null}</span>
      ))}
    </span>
  );
}

/** 유지안에만 그리는 내용 — 운영 화면에 지금 있는 조작을 유지안에서 지우지 않기 위해 쓴다. */
export function KeepOnly({ children }: { children: ReactNode }) {
  return useVariant() === "k" ? <>{children}</> : null;
}

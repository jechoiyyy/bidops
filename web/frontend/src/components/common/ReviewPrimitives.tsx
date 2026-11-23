import type {
  HTMLAttributes,
  ReactNode,
  Ref,
} from "react";
import { useId } from "react";
import { PanelRight } from "lucide-react";
import { Badge as AstryxBadge } from "@astryxdesign/core/Badge";
import { Button as AstryxButton, type ButtonProps } from "@astryxdesign/core/Button";
import { Kbd } from "@astryxdesign/core/Kbd";
import { List, ListItem } from "@astryxdesign/core/List";
import { Selector, type SelectorOptionData } from "@astryxdesign/core/Selector";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { StatusDot, type StatusDotVariant } from "@astryxdesign/core/StatusDot";
import { TabList, type TabListProps } from "@astryxdesign/core/TabList";
import { Text as AstryxText } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { EmptyState } from "./EmptyState";
import { StatusMark, type Mark } from "./Marks";

function joinClassNames(...names: Array<string | undefined | false>): string {
  return names.filter(Boolean).join(" ");
}

interface SplitWorkspaceProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  /** Slot API for new screens. Existing workspaces may pass children directly. */
  detail?: ReactNode;
  detailClassName?: string;
  detailLabel?: string;
  list?: ReactNode;
  listClassName?: string;
  listHeader?: ReactNode;
  listFooter?: ReactNode;
  listLabel?: string;
  children?: ReactNode;
}

/**
 * Master-detail workspace. Both panes stay on screen at every supported width
 * (ADR-0047: 1280~1920px). There is no narrow-width mode where the detail
 * covers the list, so selecting a row only replaces the detail pane in place
 * and never navigates.
 */
export function SplitWorkspace({
  children,
  className,
  detail,
  detailClassName,
  detailLabel = "상세",
  list,
  listClassName,
  listHeader,
  listFooter,
  listLabel = "목록",
  ...props
}: SplitWorkspaceProps) {
  return (
    <div
      {...props}
      className={joinClassNames("review-split-workspace", className)}
      data-review-primitive="split-workspace"
    >
      {children ?? (
        <>
          <section aria-label={listLabel} className={joinClassNames("review-split-list", listClassName)}>
            {listHeader}
            {list}
            {listFooter}
          </section>
          <section aria-label={detailLabel} className={joinClassNames("review-split-detail", detailClassName)}>
            <ReviewPreviewHeader />
            {detail ?? (
              <EmptyState
                className="workbench-preview-empty"
                description="목록에서 항목을 고르면 여기에서 자세히 볼 수 있어요."
                title="고른 항목이 없어요"
              />
            )}
          </section>
        </>
      )}
    </div>
  );
}

export function ReviewPreviewHeader({ position }: { position?: string }) {
  return (
    <div className="review-preview-header">
      <span><PanelRight aria-hidden="true" size={14} />미리보기</span>
      {position ? <span className="review-preview-position">{position}</span> : null}
    </div>
  );
}

export function DetailTabs({ className, ...props }: Omit<TabListProps, "hasDivider" | "role">) {
  return <TabList {...props} className={joinClassNames("workbench-detail-tabs", className)} hasDivider role="tablist" />;
}

interface AgencyFeatureProps {
  className?: string;
  /** 값이 없을 때 적을 말. 기관명을 지어내지 않고 "미확인"으로 남긴다. */
  fallback?: string;
  label?: string;
  labelClassName?: string;
  name?: string | null;
  nameClassName?: string;
  /**
   * 이름 아래 한 줄로 붙는 부제(총괄기관·공고기관 …). **블록 안**에 들어가므로
   * 배경·여백이 이름과 한 단위로 읽힌다. 값이 없으면 줄 자체를 만들지 않는다 —
   * 없는 기관을 `미제공`으로 적지 않는 판단은 부르는 쪽이 갖는다.
   */
  sub?: ReactNode;
  subClassName?: string;
}

/**
 * 발주기관 강조 블록 — 탐색 두 화면의 상세 머리가 공유한다(ADR-0062).
 *
 * 값·배경·여백은 발주계획 상세가 쓰던 것을 그대로 옮긴 것이며 새 색을 만들지
 * 않는다. 화면별 클래스(`c2l-agency-*`·`pre-specs-detail-agency`)는 검사 selector로
 * 같은 요소에 병기한다. 부제(`sub`)는 블록 안쪽 여백을 함께 쓰므로 교차 검사가
 * 재는 배경·padding은 바뀌지 않는다(`explore-workspace-consistency.spec.ts`).
 */
export function AgencyFeature({
  className,
  fallback = "발주기관 미확인",
  label = "발주기관",
  labelClassName,
  name,
  nameClassName,
  sub,
  subClassName,
}: AgencyFeatureProps) {
  const value = typeof name === "string" && name.trim() ? name : fallback;
  return (
    <div
      className={joinClassNames("review-agency-feature", className)}
      data-review-primitive="agency-feature"
    >
      <span className={joinClassNames("review-agency-label", labelClassName)}>{label}</span>
      <span className={joinClassNames("review-agency-name", nameClassName)}>{value}</span>
      {sub ? <span className={joinClassNames("review-agency-sub", subClassName)}>{sub}</span> : null}
    </div>
  );
}

interface SelectionToolbarProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  actions?: ReactNode;
  selectPage: { disabled: boolean; onClick: () => void };
  clearSelection: { disabled: boolean; onClick: () => void };
  startTracking: { disabled: boolean; onClick: () => void };
  className?: string;
  count: number;
  countClassName?: string;
  /** 오른쪽 끝의 보조 캡션(예: `이 페이지만 추가`). */
  end?: ReactNode;
  label: string;
  /** 지금 조작할 수 없는 이유. 비어 있어도 줄 높이는 유지한다. */
  reason?: ReactNode;
  reasonClassName?: string;
  reasonId?: string;
}

/**
 * 목록의 checked 묶음을 다루는 도구줄 — 두 탐색 화면이 공유한다(ADR-0062).
 *
 * 건수 자리는 폭을 고정하고 사유 줄은 비어 있어도 높이를 지켜, 선택이 늘거나
 * 줄 때 아래 목록이 위아래로 밀리지 않는다.
 */
export function SelectionToolbar({
  actions,
  selectPage,
  clearSelection,
  startTracking,
  className,
  count,
  countClassName,
  end,
  label,
  reason,
  reasonClassName,
  reasonId,
  ...props
}: SelectionToolbarProps) {
  return (
    <div
      {...props}
      aria-label={label}
      role="group"
      className={joinClassNames("review-selection-toolbar", className)}
      data-review-primitive="selection-toolbar"
    >
      <span aria-live="polite" className={joinClassNames("review-selection-count", countClassName)}>
        선택 {count.toLocaleString("ko-KR")}건
      </span>
      <button aria-label="현재 페이지 전체 선택" className="interaction-control" type="button" {...selectPage}>전체 선택</button>
      <button aria-label="선택 전체 해제" className="interaction-control" type="button" {...clearSelection}>전체 해제</button>
      {actions}
      <button
        aria-describedby={reasonId}
        className="interaction-control interaction-control-primary"
        type="button"
        {...startTracking}
      >일괄 추적 시작</button>
      {end}
      <span className={joinClassNames("review-selection-reason", reasonClassName)} id={reasonId}>
        {reason}
      </span>
    </div>
  );
}

/** 목록의 스크롤 소유자. 열 머리와 행이 같은 스크롤바 폭을 사용한다. */
export function ReviewListViewport({ className, ref, ...props }: HTMLAttributes<HTMLDivElement> & { ref?: Ref<HTMLDivElement> }) {
  return <div {...props} ref={ref} className={joinClassNames("review-list-viewport", className)} />;
}

interface ListPagerProps extends Omit<HTMLAttributes<HTMLElement>, "children"> {
  children: ReactNode;
  label: string;
}

/**
 * 페이지 이동 줄 — **목록 pane 안쪽 바닥**이다(ADR-0062: 발주계획 방식).
 *
 * 단추 자체는 화면이 갖는다(접근 가능한 이름과 조작 계약이 화면마다 이미 검사에
 * 걸려 있다). 이 primitive는 자리와 줄 배치만 소유한다.
 */
function ListPager({ children, className, label, ...props }: ListPagerProps) {
  return (
    <nav
      {...props}
      aria-label={label}
      className={joinClassNames("review-list-pager", className)}
      data-review-primitive="list-pager"
    >
      {children}
    </nav>
  );
}

/** 천 단위 구분은 한국어 로캘 하나만 쓴다(`WorkspaceFilters.formatCount`와 같은 규칙). */
function formatPagerCount(value: number): string {
  return value.toLocaleString("ko-KR");
}

interface ListPagerControlsProps {
  className?: string;
  keyboardAction?: string;
  /** 페이저 `<nav>`의 접근 이름. 화면 이름을 담는다. */
  label: string;
  /** 현재 조건의 전체 건수. */
  total: number;
  summary?: {
    /** 전체 보기와 페이지 범위의 집계 대상이 다를 때 사용한다. */
    overallTotal?: number;
    description?: string;
  };
  /** 지금 페이지의 첫 행 index(0부터). */
  offset: number;
  /** 지금 그려진 행 수. 마지막 페이지는 한 쪽 크기보다 작을 수 있다. */
  visibleCount: number;
  onPrevious: () => void;
  onNext: () => void;
  /** 일괄 작업처럼 목록 전체를 잠글 때. 양끝 비활성과 별개다. */
  isDisabled?: boolean;
}

/**
 * 목록 페이지 이동 줄의 **내용물** — 네 화면이 같은 모양을 쓴다(명세 §2.2, 시안 M1 승인).
 *
 * 왼쪽에 `전체 N건`, 오른쪽에 `1–50 / 1,234`와 이전·다음. 한 쪽에 다 들어오는 목록에서도
 * 줄을 지우지 않고 단추만 비활성한다 — 건수가 어디에 있는지 화면마다 찾지 않게 한다.
 * 자리와 줄 배치는 {@link ListPager}가 소유하므로 이 컴포넌트가 그것을 감싼다.
 */
export function ListPagerControls({
  className,
  keyboardAction,
  label,
  total,
  summary,
  offset,
  visibleCount,
  onPrevious,
  onNext,
  isDisabled = false,
}: ListPagerControlsProps) {
  const hasPrevious = offset > 0;
  const hasNext = offset + visibleCount < total;
  return (
    <ListPager className={className} label={label}>
      <div className="review-list-pager-context">
        <AstryxText className="review-list-pager-summary" type="supporting" color="secondary">
          전체 {formatPagerCount(summary?.overallTotal ?? total)}건
          {summary?.description ? ` · ${summary.description}` : null}
        </AstryxText>
        {keyboardAction ? (
          <span className="review-list-pager-keys">
            <Kbd keys="up" /> <Kbd keys="down" /> 행 이동 · <Kbd keys="mod+enter" /> {keyboardAction}
          </span>
        ) : null}
      </div>
      <div className="review-list-pager-range">
        <AstryxButton
          isDisabled={isDisabled || !hasPrevious}
          label="이전"
          onClick={onPrevious}
          size="sm"
          variant="secondary"
        />
        <AstryxText type="supporting" color="secondary">
          {visibleCount
            ? `${formatPagerCount(offset + 1)}–${formatPagerCount(Math.min(offset + visibleCount, total))} / ${formatPagerCount(total)}`
            : "표시 범위 없음"}
        </AstryxText>
        <AstryxButton
          isDisabled={isDisabled || !hasNext}
          label="다음"
          onClick={onNext}
          size="sm"
          variant="secondary"
        />
      </div>
    </ListPager>
  );
}

interface ReviewFilterBarProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  activeFilterCount?: number;
  children: ReactNode;
  onReset?: () => void;
  resetLabel?: string;
}

/** A composable filter toolbar with one shared reset affordance. */
export function ReviewFilterBar({
  activeFilterCount = 0,
  children,
  className,
  onReset,
  resetLabel = "필터 초기화",
  ...props
}: ReviewFilterBarProps) {
  const canReset = Boolean(onReset) && activeFilterCount > 0;
  return (
    <div
      {...props}
      className={joinClassNames("review-filter-bar", className)}
      data-active-filter-count={activeFilterCount}
      data-review-primitive="filter-bar"
      role="toolbar"
    >
      {children}
      {canReset ? (
        <AstryxButton
          className="review-filter-reset"
          label={resetLabel}
          onClick={onReset}
          size="sm"
          variant="ghost"
        />
      ) : null}
    </div>
  );
}

interface ReviewFilterOption {
  description?: ReactNode;
  disabled?: boolean;
  label: string;
  value: string;
}

interface ReviewFilterSelectorProps {
  className?: string;
  clearable?: boolean;
  disabledMessage?: string;
  isDisabled?: boolean;
  label: string;
  onChange: (value: string | null) => void;
  options: ReviewFilterOption[];
  placeholder?: string;
  variant?: "ghost" | "input";
  value: string | null;
}

/** Selector adapter used by filters so labels and disabled reasons stay consistent. */
export function ReviewFilterSelector({
  clearable = true,
  className,
  disabledMessage,
  isDisabled = false,
  label,
  onChange,
  options,
  placeholder = "전체",
  variant = "input",
  value,
}: ReviewFilterSelectorProps) {
  const selectorOptions: SelectorOptionData[] = options.map(({ description, disabled, label: optionLabel, value: optionValue }) => ({
    description,
    disabled,
    label: optionLabel,
    value: optionValue,
  }));
  const selectorProps = {
    className: joinClassNames("review-filter-selector", className),
    disabledMessage,
    isDisabled,
    label,
    isLabelHidden: true,
    options: selectorOptions,
    placeholder,
    size: "sm" as const,
    variant,
  };

  if (clearable) {
    return (
      <Selector
        {...selectorProps}
        data-review-primitive="filter-selector"
        hasClear
        onChange={onChange}
        value={value}
      />
    );
  }

  return (
    <Selector
      {...selectorProps}
      data-review-primitive="filter-selector"
      onChange={(next) => onChange(next)}
      value={value ?? undefined}
    />
  );
}

interface ReviewFilterSegmentedOption {
  disabled?: boolean;
  label: string;
  value: string;
}

interface ReviewFilterSegmentedControlProps {
  className?: string;
  disabledMessage?: string;
  isDisabled?: boolean;
  label: string;
  /**
   * Astryx `SegmentedControl`의 폭 정책을 그대로 넘긴다. `fill`은 `width: 100%`라
   * 컨테이너를 통째로 차지하므로 필터 바 같은 flex 도구 줄에서는 혼자 한 줄을
   * 먹는다. 그 줄에 놓는 컨트롤은 `hug`를 준다. 기본값은 기존 동작(`fill`)이다.
   * @default "fill"
   */
  layout?: "hug" | "fill";
  onChange: (value: string) => void;
  options: ReviewFilterSegmentedOption[];
  value: string;
}

/** Segmented control adapter for saved views and other single-choice filters. */
export function ReviewFilterSegmentedControl({
  className,
  disabledMessage,
  isDisabled = false,
  label,
  layout = "fill",
  onChange,
  options,
  value,
}: ReviewFilterSegmentedControlProps) {
  return (
    <SegmentedControl
      className={joinClassNames("review-filter-segmented", className)}
      data-review-primitive="segmented-control"
      disabledMessage={disabledMessage}
      isDisabled={isDisabled}
      label={label}
      layout={layout}
      onChange={onChange}
      size="sm"
      value={value}
    >
      {options.map((option) => (
        <SegmentedControlItem
          isDisabled={option.disabled}
          key={option.value}
          label={option.label}
          value={option.value}
        />
      ))}
    </SegmentedControl>
  );
}

interface ReviewFilterTextInputProps {
  className?: string;
  disabledMessage?: string;
  isDisabled?: boolean;
  label: string;
  onChange: (value: string) => void;
  onEnter?: () => void;
  placeholder?: string;
  value: string;
}

/** TextInput adapter for search filters with a consistently hidden label. */
export function ReviewFilterTextInput({
  className,
  disabledMessage,
  isDisabled = false,
  label,
  onChange,
  onEnter,
  placeholder,
  value,
}: ReviewFilterTextInputProps) {
  return (
    <TextInput
      className={joinClassNames("review-filter-text-input", className)}
      data-review-primitive="text-input"
      disabledMessage={disabledMessage}
      hasClear
      isDisabled={isDisabled}
      isLabelHidden
      label={label}
      onChange={onChange}
      onEnter={onEnter}
      placeholder={placeholder}
      size="sm"
      value={value}
    />
  );
}

interface ReviewStatusProps {
  className?: string;
  detail?: ReactNode;
  isPulsing?: boolean;
  label: string;
  tooltip?: string;
  variant: StatusDotVariant;
}

/** StatusDot paired with a visible label so status is never colour-only. */
function ReviewStatus({
  className,
  detail,
  isPulsing = false,
  label,
  tooltip,
  variant,
}: ReviewStatusProps) {
  return (
    <span className={joinClassNames("review-status", className)} data-review-primitive="status" data-status-variant={variant}>
      <StatusDot isPulsing={isPulsing} label={label} tooltip={tooltip} variant={variant} />
      <span className="review-status-label">{label}</span>
      {detail !== undefined ? <span className="review-status-detail">{detail}</span> : null}
    </span>
  );
}

type ReviewValueState = "value" | "unknown" | "null";

interface ReviewValueProps {
  className?: string;
  nullLabel?: string;
  state?: ReviewValueState;
  unknownLabel?: string;
  value?: ReactNode;
}

/** Explicitly distinguishes values, unknown values, and null values. */
export function ReviewValue({
  className,
  nullLabel = "null · 값 없음",
  state: stateProp,
  unknownLabel = "unknown · 확인 대기",
  value,
}: ReviewValueProps) {
  const state = stateProp ?? (value === undefined || value === null ? "null" : "value");
  const content = state === "unknown"
    ? unknownLabel
    : state === "null"
      ? nullLabel
      : typeof value === "boolean"
        ? String(value)
        : value;
  return (
    <span className={joinClassNames("review-value", `is-${state}`, className)} data-review-primitive="value" data-value-state={state}>
      {content}
    </span>
  );
}

interface StickyDecisionHeaderProps extends Omit<HTMLAttributes<HTMLElement>, "children"> {
  actions?: ReactNode;
  children: ReactNode;
  label?: string;
}

/** Header primitive that keeps decision actions reachable while the body scrolls. */
export function StickyDecisionHeader({
  actions,
  children,
  className,
  label,
  ...props
}: StickyDecisionHeaderProps) {
  return (
    <header
      {...props}
      aria-label={label}
      className={joinClassNames("review-sticky-decision-header", className)}
      data-review-primitive="sticky-decision-header"
      data-sticky="true"
    >
      {children}
      {actions}
    </header>
  );
}

function DecisionBarFrame({ children, label, ...props }: HTMLAttributes<HTMLElement> & { label: string }) {
  return (
    <footer {...props} aria-label={label} data-review-primitive="decision-bar" role="group">
      {children}
    </footer>
  );
}

interface DecisionBarProps {
  className?: string;
  label?: string;
  id?: string;
  stateClassName?: string;
  stateLabel: string;
  state: Mark;
  actorAction?: ReactNode;
  note?: ReactNode;
  secondaryActions?: ReactNode;
  primaryAction?: ReactNode;
  content?: ReactNode;
}

export function DecisionBar({ className, label = "결정 영역", id, stateClassName, stateLabel, state, actorAction, note, secondaryActions, primaryAction, content }: DecisionBarProps) {
  return (
    <DecisionBarFrame className={joinClassNames("workbench-decision", className)} id={id} label={label}>
      {content ? <div className="workbench-decision-content">{content}</div> : null}
      <div className={joinClassNames("workbench-decision-state", stateClassName)}>
        <div className="workbench-decision-status">
          <span>{stateLabel}</span>
          <StatusMark mark={state} />
        </div>
        {actorAction}
        {note ? <p className="workbench-decision-note">{note}</p> : null}
      </div>
      {secondaryActions || primaryAction ? (
        <div className="workbench-decision-actions">
          {secondaryActions}
          {primaryAction}
        </div>
      ) : null}
    </DecisionBarFrame>
  );
}

interface ReviewRevisionEntry {
  /** Who claimed the change. An audit marker, never an authenticated identity. */
  actor?: ReactNode;
  at?: ReactNode;
  body?: ReactNode;
  id: string | number;
  revision: number;
  /** The recorded values, e.g. relevance and priority tokens. */
  tags?: ReactNode;
}

interface ReviewRevisionHistoryProps {
  appendOnlyLabel?: string;
  className?: string;
  empty?: ReactNode;
  /** Newest first. The primitive preserves the caller's order rather than sorting. */
  entries: ReviewRevisionEntry[];
  error?: ReactNode;
  /** Depends on what already surrounds it — a rail section sits under an h3. */
  headingLevel?: 3 | 4 | 5;
  label: string;
}

/**
 * Append-only revision history for a secondary input.
 *
 * Revisions are added, never edited or replaced, so the count and the
 * append-only marker are part of the reading — a shrinking count means the
 * server lost history, not that a person tidied it up.
 */
export function ReviewRevisionHistory({
  appendOnlyLabel = "append-only",
  className,
  empty,
  entries,
  error,
  headingLevel = 4,
  label,
}: ReviewRevisionHistoryProps) {
  const titleId = `review-revision-history-${useId().replace(/:/g, "")}`;
  const Heading = `h${headingLevel}` as const;
  return (
    <section
      aria-labelledby={titleId}
      className={joinClassNames("review-revision-history", className)}
      data-review-primitive="revision-history"
      data-revision-count={entries.length}
    >
      <header className="review-revision-history-head">
        <Heading className="review-revision-history-title" id={titleId}>{label}</Heading>
        <AstryxBadge label={`${appendOnlyLabel} · ${entries.length.toLocaleString("ko-KR")}건`} variant="neutral" />
      </header>
      {error ? <p className="review-revision-history-error" role="alert">{error}</p> : null}
      {entries.length === 0 ? (
        <p className="review-revision-history-empty">{empty ?? "기록된 수정본이 없어요."}</p>
      ) : (
        <List className="review-revision-history-list" density="compact" hasDividers>
          {entries.map((entry) => (
            <ListItem
              className="review-revision-history-entry"
              data-revision={entry.revision}
              description={entry.body}
              endContent={entry.at !== undefined || entry.actor !== undefined ? (
                <span className="review-revision-history-meta">
                  {entry.at}
                  {entry.at !== undefined && entry.actor !== undefined ? " · " : null}
                  {entry.actor}
                </span>
              ) : undefined}
              key={entry.id}
              label={(
                <span className="review-revision-history-label">
                  <AstryxBadge label={`revision ${entry.revision}`} variant="neutral" />
                  {entry.tags}
                </span>
              )}
            />
          ))}
        </List>
      )}
    </section>
  );
}

interface ReviewEvidenceItem {
  detail?: ReactNode;
  id: string | number;
  locator?: ReactNode;
  startContent?: ReactNode;
  title: ReactNode;
  tone?: "neutral" | "warning" | "error" | "accent";
}

interface ReviewEvidenceListProps {
  className?: string;
  empty?: ReactNode;
  items: ReviewEvidenceItem[];
  label: string;
}

/** Repeating evidence rows with an explicit locator slot for source links. */
export function ReviewEvidenceList({ className, empty, items, label }: ReviewEvidenceListProps) {
  if (items.length === 0) {
    return (
      <div
        className={joinClassNames("review-evidence-list-empty", className)}
        data-review-primitive="evidence-list"
      >
        {empty ?? "근거 항목이 없어요."}
      </div>
    );
  }
  return (
    <List aria-label={label} className={joinClassNames("review-evidence-list", className)} data-review-primitive="evidence-list" density="compact" hasDividers>
      {items.map((item) => (
        <ListItem
          className={item.tone ? `is-${item.tone}` : undefined}
          description={item.detail}
          endContent={item.locator}
          key={item.id}
          label={item.title}
          startContent={item.startContent}
        />
      ))}
    </List>
  );
}

interface ReviewHistoryEntry {
  detail?: ReactNode;
  id: string | number;
  label: ReactNode;
  status?: { label: string; variant: StatusDotVariant };
}

interface ReviewRailLink {
  href: string;
  label: string;
  external?: boolean;
}

interface ReviewHistorySection {
  className?: string;
  content?: ReactNode;
  empty?: ReactNode;
  entries: ReviewHistoryEntry[];
  error?: ReactNode;
  label: string;
  listClassName?: string;
  showHeading?: boolean;
}

interface ReviewHistoryLinkRailProps {
  className?: string;
  history?: ReviewHistoryEntry[];
  historySections?: ReviewHistorySection[];
  historyLabel?: string;
  links?: ReviewRailLink[];
  linksClassName?: string;
  linksLabel?: string;
  title?: string;
  footer?: ReactNode;
}

/** Shared right rail for history and related links; it never owns decisions. */
export function ReviewHistoryLinkRail({
  className,
  history = [],
  historySections,
  historyLabel = "변경 이력",
  links = [],
  linksClassName,
  linksLabel = "연결된 화면",
  title = "이력과 연결",
  footer,
}: ReviewHistoryLinkRailProps) {
  const sections = historySections ?? [{ entries: history, label: historyLabel }];
  return (
    <aside aria-label={title} className={joinClassNames("review-history-link-rail", className)} data-review-primitive="history-link-rail">
      <h3>{title}</h3>
      {sections.map((section) => (
        <section aria-label={section.label} className={section.className} key={section.label}>
          {section.showHeading !== false ? <h4>{section.label}</h4> : null}
          {section.content !== undefined ? section.content : (
            <>
              {section.error ? <p className="review-history-error" role="alert">{section.error}</p> : null}
              {section.entries.length > 0 ? (
                <List className={joinClassNames("review-history-list", section.listClassName)} data-review-primitive="history-list" density="compact">
                  {section.entries.map((entry) => (
                    <ListItem
                      key={entry.id}
                      label={entry.label}
                      description={entry.detail}
                      startContent={entry.status ? <ReviewStatus label={entry.status.label} variant={entry.status.variant} /> : undefined}
                    />
                  ))}
                </List>
              ) : (
                <p className="review-history-empty">{section.empty ?? "이력이 없어요."}</p>
              )}
            </>
          )}
        </section>
      ))}
      {links.length > 0 ? (
        <nav aria-label={linksLabel} className={joinClassNames("review-rail-links", linksClassName)}>
          <h4>{linksLabel}</h4>
          <List data-review-primitive="rail-links" density="compact">
            {links.map((link) => (
              <ListItem
                href={link.href}
                key={`${link.href}-${link.label}`}
                label={link.label}
                rel={link.external ? "noreferrer" : undefined}
                target={link.external ? "_blank" : undefined}
              />
            ))}
          </List>
        </nav>
      ) : null}
      {footer}
    </aside>
  );
}

interface ReviewDecisionActionProps extends Omit<ButtonProps, "children" | "isDisabled" | "label"> {
  disabledReason?: ReactNode;
  disabledReasonId?: string;
  isDisabled?: boolean;
  label: string;
}

/**
 * A decision button that keeps the reason for a disabled action adjacent and
 * discoverable. The button itself remains an Astryx control; this wrapper only
 * owns the product's disabled-reason contract.
 */
export function ReviewDecisionAction({
  "aria-describedby": ariaDescribedBy,
  className,
  disabledReason,
  disabledReasonId,
  isDisabled = false,
  label,
  ...props
}: ReviewDecisionActionProps) {
  const generatedReasonId = `review-decision-reason-${useId().replace(/:/g, "")}`;
  const reasonId = disabledReasonId ?? generatedReasonId;
  const hasReason = isDisabled && disabledReason !== undefined && disabledReason !== null;
  // Several actions in one bar can share the same reason. The owner renders the
  // text once; the others point at that id so the reason is still announced
  // without repeating it on screen three times.
  const describesReason = isDisabled && (hasReason || disabledReasonId !== undefined);
  const describedBy = [ariaDescribedBy, describesReason ? reasonId : undefined].filter(Boolean).join(" ") || undefined;
  return (
    <span className="review-decision-action" data-review-primitive="decision-action">
      <AstryxButton
        {...props}
        aria-describedby={describedBy}
        className={className}
        isDisabled={isDisabled}
        label={label}
      />
      {hasReason ? <span className="review-decision-action-reason" id={reasonId}>{disabledReason}</span> : null}
    </span>
  );
}

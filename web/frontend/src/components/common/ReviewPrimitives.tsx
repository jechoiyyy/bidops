import type {
  HTMLAttributes,
  ReactNode,
  Ref,
} from "react";
import { Badge as AstryxBadge } from "@astryxdesign/core/Badge";
import { Banner as AstryxBanner } from "@astryxdesign/core/Banner";
import { Button as AstryxButton } from "@astryxdesign/core/Button";
import { Collapsible as AstryxCollapsible } from "@astryxdesign/core/Collapsible";
import { EmptyState as AstryxEmptyState } from "@astryxdesign/core/EmptyState";
import { List, ListItem, type ListItemProps } from "@astryxdesign/core/List";
import { Selector, type SelectorOptionData } from "@astryxdesign/core/Selector";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { StatusDot, type StatusDotVariant } from "@astryxdesign/core/StatusDot";
import { TextInput } from "@astryxdesign/core/TextInput";

function joinClassNames(...names: Array<string | undefined | false>): string {
  return names.filter(Boolean).join(" ");
}

/**
 * Dense list container shared by review screens.
 *
 * Records stay rows rather than individual cards. Astryx owns the list/item
 * interaction and density; the product only adds the domain class used for
 * its list-pane layout.
 */
export interface DenseListProps extends Omit<HTMLAttributes<HTMLUListElement>, "children"> {
  children: ReactNode;
}

export function DenseList({ children, className, ...props }: DenseListProps) {
  return (
    <List
      {...props}
      className={joinClassNames("review-dense-list", className)}
      density="compact"
      hasDividers
    >
      {children}
    </List>
  );
}

export interface DenseListRowProps extends Omit<
  ListItemProps,
  "description" | "endContent" | "isDisabled" | "isSelected" | "label" | "onClick" | "startContent"
> {
  description?: ReactNode;
  endContent?: ReactNode;
  label: ReactNode;
  onSelect?: () => void;
  selected?: boolean;
  startContent?: ReactNode;
  disabled?: boolean;
  ref?: Ref<HTMLLIElement>;
}

/** A selected, keyboard-operable dense row for a master list. */
export function DenseListRow({
  className,
  description,
  disabled = false,
  endContent,
  label,
  onSelect,
  ref,
  selected = false,
  startContent,
  ...props
}: DenseListRowProps) {
  return (
    <ListItem
      {...props}
      aria-current={selected ? "true" : undefined}
      className={joinClassNames("review-dense-list-row", selected && "is-selected", className)}
      description={description}
      endContent={endContent}
      isDisabled={disabled}
      isSelected={selected}
      label={label}
      onClick={onSelect ? () => onSelect() : undefined}
      ref={ref}
      startContent={startContent}
    />
  );
}

export type SplitMobileView = "list" | "detail";

export interface SplitWorkspaceProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  detail: ReactNode;
  detailLabel: string;
  list: ReactNode;
  listLabel: string;
  mobileView?: SplitMobileView;
}

/**
 * Master-detail workspace. The wrapper regions use display: contents on wide
 * screens so existing list/detail panes keep their width budget. At the
 * narrow breakpoint one region is hidden, so the detail view can cover the
 * list without navigating to another page.
 */
export function SplitWorkspace({
  className,
  detail,
  detailLabel,
  list,
  listLabel,
  mobileView,
  ...props
}: SplitWorkspaceProps) {
  return (
    <div
      {...props}
      className={joinClassNames("review-split-workspace", className)}
      data-mobile-view={mobileView}
    >
      <section aria-label={listLabel} className="review-split-list">
        {list}
      </section>
      <section aria-label={detailLabel} className="review-split-detail">
        {detail}
      </section>
    </div>
  );
}

export interface ReviewFilterBarProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
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

export interface ReviewFilterOption {
  description?: ReactNode;
  disabled?: boolean;
  label: string;
  value: string;
}

export interface ReviewFilterSelectorProps {
  className?: string;
  disabledMessage?: string;
  isDisabled?: boolean;
  label: string;
  onChange: (value: string | null) => void;
  options: ReviewFilterOption[];
  placeholder?: string;
  value: string | null;
}

/** Selector adapter used by filters so labels and disabled reasons stay consistent. */
export function ReviewFilterSelector({
  className,
  disabledMessage,
  isDisabled = false,
  label,
  onChange,
  options,
  placeholder = "전체",
  value,
}: ReviewFilterSelectorProps) {
  const selectorOptions: SelectorOptionData[] = options.map(({ description, disabled, label: optionLabel, value: optionValue }) => ({
    description,
    disabled,
    label: optionLabel,
    value: optionValue,
  }));
  return (
    <Selector
      className={joinClassNames("review-filter-selector", className)}
      disabledMessage={disabledMessage}
      hasClear
      isDisabled={isDisabled}
      label={label}
      isLabelHidden
      onChange={onChange}
      options={selectorOptions}
      placeholder={placeholder}
      size="sm"
      value={value}
    />
  );
}

export interface ReviewFilterSegmentedOption {
  disabled?: boolean;
  label: string;
  value: string;
}

export interface ReviewFilterSegmentedControlProps {
  className?: string;
  disabledMessage?: string;
  isDisabled?: boolean;
  label: string;
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
  onChange,
  options,
  value,
}: ReviewFilterSegmentedControlProps) {
  return (
    <SegmentedControl
      className={joinClassNames("review-filter-segmented", className)}
      disabledMessage={disabledMessage}
      isDisabled={isDisabled}
      label={label}
      layout="fill"
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

export interface ReviewFilterTextInputProps {
  className?: string;
  disabledMessage?: string;
  isDisabled?: boolean;
  label: string;
  onChange: (value: string) => void;
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
  placeholder,
  value,
}: ReviewFilterTextInputProps) {
  return (
    <TextInput
      className={joinClassNames("review-filter-text-input", className)}
      disabledMessage={disabledMessage}
      hasClear
      isDisabled={isDisabled}
      isLabelHidden
      label={label}
      onChange={onChange}
      placeholder={placeholder}
      size="sm"
      value={value}
    />
  );
}

export interface ReviewStatusProps {
  className?: string;
  detail?: ReactNode;
  isPulsing?: boolean;
  label: string;
  tooltip?: string;
  variant: StatusDotVariant;
}

/** StatusDot paired with a visible label so status is never colour-only. */
export function ReviewStatus({
  className,
  detail,
  isPulsing = false,
  label,
  tooltip,
  variant,
}: ReviewStatusProps) {
  return (
    <span className={joinClassNames("review-status", className)} data-status-variant={variant}>
      <StatusDot isPulsing={isPulsing} label={label} tooltip={tooltip} variant={variant} />
      <span className="review-status-label">{label}</span>
      {detail !== undefined ? <span className="review-status-detail">{detail}</span> : null}
    </span>
  );
}

export type ReviewValueState = "value" | "unknown" | "null";

export interface ReviewValueProps {
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
    <span className={joinClassNames("review-value", `is-${state}`, className)} data-value-state={state}>
      {content}
    </span>
  );
}

export interface StickyDecisionHeaderProps extends Omit<HTMLAttributes<HTMLElement>, "children"> {
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
      data-sticky="true"
    >
      {children}
      {actions}
    </header>
  );
}

export interface ReviewEvidenceItem {
  detail?: ReactNode;
  id: string | number;
  locator?: ReactNode;
  title: ReactNode;
  tone?: "neutral" | "warning" | "error" | "accent";
}

export interface ReviewEvidenceListProps {
  className?: string;
  empty?: ReactNode;
  items: ReviewEvidenceItem[];
  label: string;
}

/** Repeating evidence rows with an explicit locator slot for source links. */
export function ReviewEvidenceList({ className, empty, items, label }: ReviewEvidenceListProps) {
  if (items.length === 0) {
    return <div className={joinClassNames("review-evidence-list-empty", className)}>{empty ?? "근거 항목이 없습니다."}</div>;
  }
  return (
    <ul aria-label={label} className={joinClassNames("review-evidence-list", className)}>
      {items.map((item) => (
        <li className={item.tone ? `is-${item.tone}` : undefined} key={item.id}>
          <strong>{item.title}</strong>
          {item.detail !== undefined ? <span className="review-evidence-detail">{item.detail}</span> : null}
          {item.locator !== undefined ? <span className="review-evidence-locator">{item.locator}</span> : null}
        </li>
      ))}
    </ul>
  );
}

export interface ReviewHistoryEntry {
  detail?: ReactNode;
  id: string | number;
  label: ReactNode;
  status?: { label: string; variant: StatusDotVariant };
}

export interface ReviewRailLink {
  href: string;
  label: string;
  external?: boolean;
}

export interface ReviewHistoryLinkRailProps {
  className?: string;
  history?: ReviewHistoryEntry[];
  historyLabel?: string;
  links?: ReviewRailLink[];
  linksLabel?: string;
  title?: string;
}

/** Shared right rail for history and related links; it never owns decisions. */
export function ReviewHistoryLinkRail({
  className,
  history = [],
  historyLabel = "변경 이력",
  links = [],
  linksLabel = "연결된 화면",
  title = "이력과 연결",
}: ReviewHistoryLinkRailProps) {
  return (
    <aside aria-label={title} className={joinClassNames("review-history-link-rail", className)}>
      <h3>{title}</h3>
      {history.length > 0 ? (
        <section aria-label={historyLabel}>
          <h4>{historyLabel}</h4>
          <ol className="review-history-list">
            {history.map((entry) => (
              <li key={entry.id}>
                {entry.status ? <ReviewStatus label={entry.status.label} variant={entry.status.variant} /> : null}
                <strong>{entry.label}</strong>
                {entry.detail !== undefined ? <span>{entry.detail}</span> : null}
              </li>
            ))}
          </ol>
        </section>
      ) : (
        <p className="review-history-empty">이력이 없습니다.</p>
      )}
      {links.length > 0 ? (
        <nav aria-label={linksLabel} className="review-rail-links">
          <h4>{linksLabel}</h4>
          <ul>
            {links.map((link) => (
              <li key={`${link.href}-${link.label}`}>
                <a href={link.href} rel={link.external ? "noreferrer" : undefined} target={link.external ? "_blank" : undefined}>
                  {link.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      ) : null}
    </aside>
  );
}

export interface ReviewStateProps {
  action?: ReactNode;
  children?: ReactNode;
  className?: string;
  description: string;
  kind: "empty" | "partial" | "failure";
  title: string;
}

/** Shared empty/partial/failure language; it never turns a failed result into empty data. */
export function ReviewState({ action, children, className, description, kind, title }: ReviewStateProps) {
  if (kind === "empty") {
    return (
      <AstryxEmptyState
        actions={action}
        className={joinClassNames("review-state", "is-empty", className)}
        description={description}
        headingLevel={3}
        isCompact
        title={title}
      />
    );
  }
  return (
    <AstryxBanner
      className={joinClassNames("review-state", `is-${kind}`, className)}
      collapsible={children ? { defaultIsOpen: false } : false}
      description={description}
      endContent={action}
      status={kind === "failure" ? "error" : "warning"}
      title={title}
    >
      {children}
    </AstryxBanner>
  );
}

export interface ReviewStateGroupProps {
  children: ReactNode;
  count: number | null;
  defaultIsOpen?: boolean;
  disabledMessage?: string;
  isDisabled?: boolean;
  label: ReactNode;
  status?: { label: string; variant: StatusDotVariant };
  value: string;
}

/** Collapsible status group with a count that preserves zero and unknown. */
export function ReviewStateGroup({
  children,
  count,
  defaultIsOpen = false,
  disabledMessage,
  isDisabled = false,
  label,
  status,
  value,
}: ReviewStateGroupProps) {
  const countLabel = count === null ? <ReviewValue state="unknown" /> : `${count.toLocaleString("ko-KR")}건`;
  return (
    <div className="review-state-group" data-group-value={value}>
      <AstryxCollapsible
        data-testid={`review-state-group-${value}`}
        defaultIsOpen={defaultIsOpen}
        isDisabled={isDisabled}
        trigger={
          <span className="review-state-group-trigger">
            {status ? <StatusDot label={status.label} variant={status.variant} /> : null}
            <span className="review-state-group-label">{label}</span>
            <AstryxBadge label={countLabel} variant="neutral" />
          </span>
        }
        value={value}
      >
        <div className="review-state-group-content">{children}</div>
      </AstryxCollapsible>
      {isDisabled && disabledMessage ? <p className="review-state-group-disabled-reason">{disabledMessage}</p> : null}
    </div>
  );
}

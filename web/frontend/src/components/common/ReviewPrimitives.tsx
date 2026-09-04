import type {
  HTMLAttributes,
  KeyboardEvent as ReactKeyboardEvent,
  MouseEvent as ReactMouseEvent,
  ReactNode,
  Ref,
} from "react";
import { useId } from "react";
import { Badge as AstryxBadge } from "@astryxdesign/core/Badge";
import { Banner as AstryxBanner } from "@astryxdesign/core/Banner";
import { Button as AstryxButton, type ButtonProps } from "@astryxdesign/core/Button";
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
      data-review-primitive="dense-list"
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
  onKeyDown,
  role,
  ref,
  selected = false,
  startContent,
  tabIndex,
  ...props
}: DenseListRowProps) {
  const rowRole = role ?? (onSelect ? "button" : undefined);
  const handleClick = (event: ReactMouseEvent<Element>) => {
    if (disabled || !onSelect) return;
    const target = event.target;
    if (target instanceof Element && target.closest("a,button,input,select,textarea")) return;
    onSelect();
  };
  const handleKeyDown = (event: ReactKeyboardEvent<HTMLLIElement>) => {
    onKeyDown?.(event);
    if (event.defaultPrevented || disabled || !onSelect) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect();
    }
  };
  return (
    <ListItem
      {...props}
      aria-current={selected ? "true" : undefined}
      className={joinClassNames("review-dense-list-row", selected && "is-selected", className)}
      data-review-primitive="dense-list-row"
      description={description}
      endContent={endContent}
      isDisabled={disabled}
      isSelected={selected}
      label={label}
      onClick={onSelect ? handleClick : undefined}
      onKeyDown={onSelect ? handleKeyDown : onKeyDown}
      ref={ref}
      role={rowRole}
      startContent={startContent}
      tabIndex={rowRole ? (disabled ? -1 : tabIndex ?? 0) : tabIndex}
    />
  );
}

export type SplitMobileView = "list" | "detail";

export interface SplitWorkspaceProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  /** Slot API for new screens. Existing workspaces may pass children directly. */
  detail?: ReactNode;
  detailLabel?: string;
  list?: ReactNode;
  listLabel?: string;
  mobileView?: SplitMobileView;
  children?: ReactNode;
}

/**
 * Master-detail workspace. The wrapper regions use display: contents on wide
 * screens so existing list/detail panes keep their width budget. At the
 * narrow breakpoint one region is hidden, so the detail view can cover the
 * list without navigating to another page.
 */
export function SplitWorkspace({
  children,
  className,
  detail,
  detailLabel = "상세",
  list,
  listLabel = "목록",
  mobileView,
  ...props
}: SplitWorkspaceProps) {
  return (
    <div
      {...props}
      className={joinClassNames("review-split-workspace", className)}
      data-mobile-view={mobileView}
      data-review-primitive="split-workspace"
    >
      {children ?? (
        <>
          <section aria-label={listLabel} className="review-split-list">
            {list}
          </section>
          <section aria-label={detailLabel} className="review-split-detail">
            {detail}
          </section>
        </>
      )}
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

export interface ReviewFilterOption {
  description?: ReactNode;
  disabled?: boolean;
  label: string;
  value: string;
}

export interface ReviewFilterSelectorProps {
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
      data-review-primitive="segmented-control"
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
    <span className={joinClassNames("review-status", className)} data-review-primitive="status" data-status-variant={variant}>
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
    <span className={joinClassNames("review-value", `is-${state}`, className)} data-review-primitive="value" data-value-state={state}>
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
      data-review-primitive="sticky-decision-header"
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
  startContent?: ReactNode;
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
    return (
      <div
        className={joinClassNames("review-evidence-list-empty", className)}
        data-review-primitive="evidence-list"
      >
        {empty ?? "근거 항목이 없습니다."}
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

export interface ReviewHistorySection {
  className?: string;
  content?: ReactNode;
  empty?: ReactNode;
  entries: ReviewHistoryEntry[];
  error?: ReactNode;
  label: string;
  listClassName?: string;
  showHeading?: boolean;
}

export interface ReviewHistoryLinkRailProps {
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
                <p className="review-history-empty">{section.empty ?? "이력이 없습니다."}</p>
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
        data-review-primitive="state"
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
      data-review-primitive="state"
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
        data-review-primitive="state-group"
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

export interface ReviewDecisionActionProps extends Omit<ButtonProps, "children" | "isDisabled" | "label"> {
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
  const describedBy = [ariaDescribedBy, hasReason ? reasonId : undefined].filter(Boolean).join(" ") || undefined;
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

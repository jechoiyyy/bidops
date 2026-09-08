import type { CSSProperties, HTMLAttributes, ReactNode } from "react";
import { Button } from "@astryxdesign/core/Button";
import { TextInput } from "@astryxdesign/core/TextInput";
import { ListFilter, Search } from "lucide-react";

/**
 * 탐색과 추적 4화면(발주계획·사전규격·사업 추적·최종 Go/No-Go)이 공유하는 필터 바.
 *
 * 기준 UI는 사업 추적 화면이고 프레임 값(배경·테두리·radius·padding)은 발주계획이다
 * (계획서 §2·§3). 단일 props 컴포넌트가 아니라 **조합형**인 이유는 세 화면의 요구가
 * 서로 겹치지 않기 때문이다 — 발주계획은 4축 토글과 저장된 뷰를, 사전규격은 둘째 줄
 * 스위치·안내 노트를, Go/No-Go는 상세 필터 없이 즉시 검색만 필요로 한다.
 *
 * 이 파일은 **골격과 접근성 계약만** 소유한다. 필터 축의 집합, URL 파라미터 이름,
 * AND/OR 의미, 검색을 즉시 적용할지 Enter로 적용할지는 전부 화면이 정한다
 * (화면이 서버 응답을 다시 판정하지 않는다는 규칙과 같은 이유).
 *
 * 모든 컴포넌트는 `className`을 받아 화면 접두 클래스를 덧붙일 수 있다. 기존 spec이
 * `.opportunity-view-tabs`·`.gng-view-tabs`·`.pre-specs-views` 같은 화면 클래스로
 * 요소를 찾으므로, 채택할 때 그 이름을 그대로 넘긴다.
 */

function joinClassNames(...names: Array<string | undefined | false>): string {
  return names.filter(Boolean).join(" ");
}

/** 보기 탭·목록 건수의 숫자 표기. 세 자리 구분은 한국어 로캘 하나만 쓴다. */
function formatCount(count: number): string {
  return count.toLocaleString("ko-KR");
}

export interface WorkspaceFrameProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  children: ReactNode;
}

/**
 * 필터 바와 workspace(목록+상세)를 한 덩어리로 묶는 세로 flex 컨테이너.
 *
 * 필터 바와 workspace 사이 간격을 화면마다 다르게 두지 않으려고 존재한다
 * (`c2l-workspace-shell`·`pre-specs-workspace-shell`을 대체한다). 남은 높이를 전부
 * 차지하고 `min-height: 0`이라 스크롤은 안쪽 pane에서만 일어난다.
 */
export function WorkspaceFrame({ children, className, ...props }: WorkspaceFrameProps) {
  return (
    <div {...props} className={joinClassNames("workspace-frame", className)} data-review-primitive="workspace-frame">
      {children}
    </div>
  );
}

export interface WorkspaceFilterBarProps extends Omit<HTMLAttributes<HTMLElement>, "children"> {
  /**
   * 접혀 있는 상세 필터까지 포함해 지금 걸려 있는 필터 수. 세는 방법은 화면이
   * 소유하고, 세지 않는 화면은 넘기지 않는다(0으로 채워 "필터 없음"이라고 말하지
   * 않는다).
   */
  activeFilterCount?: number;
  children: ReactNode;
}

/**
 * 필터 바 컨테이너. `<section aria-label>`이므로 landmark(region)로 노출된다.
 *
 * `role="toolbar"`를 쓰지 않는다: toolbar는 화살표 키로 내부를 이동하는 단일 tab stop
 * 위젯이고, 이 바는 탭·검색·토글이 각각 tab stop인 보통의 컨트롤 묶음이다.
 * `review-primitives.spec.ts`는 role이 아니라 `data-review-primitive="filter-bar"`로
 * 찾으므로 그대로 통과한다.
 */
export function WorkspaceFilterBar({
  activeFilterCount,
  children,
  className,
  ...props
}: WorkspaceFilterBarProps) {
  return (
    <section
      {...props}
      className={joinClassNames("workspace-filters", className)}
      data-active-filter-count={activeFilterCount === undefined ? undefined : String(activeFilterCount)}
      data-review-primitive="filter-bar"
    >
      {children}
    </section>
  );
}

export interface WorkspaceFilterLineProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  children: ReactNode;
}

/**
 * 필터 바의 첫 줄. 왼쪽은 보기 탭({@link WorkspaceViewTabs}), 오른쪽은 검색과 상세
 * 필터 토글({@link WorkspaceFilterEnd})이다(space-between).
 */
export function WorkspaceFilterLine({ children, className, ...props }: WorkspaceFilterLineProps) {
  return (
    <div {...props} className={joinClassNames("workspace-filter-line", className)}>
      {children}
    </div>
  );
}

export interface WorkspaceViewTab<K extends string> {
  /** URL·상태에 쓰는 값. 라벨과 달리 번역·표기 변경의 영향을 받지 않는다. */
  key: K;
  label: string;
  /**
   * 탭 옆 건수. `undefined`면 건수를 아예 표시하지 않고, `null`이면 `–`로 그린다
   * (아직 못 불러온 상태와 0건은 서로 다른 사실이다).
   */
  count?: number | null;
}

export interface WorkspaceViewTabsProps<K extends string> {
  className?: string;
  /** 탭 묶음의 접근 이름. `<div role="group" aria-label>`에 붙는다. */
  label: string;
  onChange: (key: K) => void;
  tabs: readonly WorkspaceViewTab<K>[];
  value: K;
}

/**
 * 보기 탭. 라디오 그룹이 아니라 `aria-pressed`를 가진 버튼 묶음이다.
 *
 * 버튼을 쓰는 이유: 탭은 "지금 목록에 무엇이 담겨 있는가"를 바꾸는 지름길이고
 * 화면의 다른 필터 축과 함께 걸린다. 라디오로 그리면 축이 하나뿐이라는 뜻이 되고,
 * `role="tab"`으로 그리면 tabpanel 계약(패널 하나가 탭에 종속)을 만들어야 한다.
 *
 * 라벨은 `${label}  ${count}`(두 칸)이다. Astryx `Button`의 `label`은 문자열이라
 * 건수를 별도 요소로 꾸밀 수 없고, 두 칸이 시각적 구분을 대신한다. 건수는 접근 이름의
 * 일부이므로 테스트는 `getByRole("button", { name: /^전체/ })`처럼 앞부분으로 찾는다.
 */
export function WorkspaceViewTabs<K extends string>({
  className,
  label,
  onChange,
  tabs,
  value,
}: WorkspaceViewTabsProps<K>) {
  return (
    <div aria-label={label} className={joinClassNames("workspace-view-tabs", className)} role="group">
      {tabs.map((tab) => (
        <Button
          aria-pressed={value === tab.key}
          data-view-key={tab.key}
          key={tab.key}
          label={
            tab.count === undefined
              ? tab.label
              : `${tab.label}  ${tab.count === null ? "–" : formatCount(tab.count)}`
          }
          onClick={() => onChange(tab.key)}
          size="sm"
        />
      ))}
    </div>
  );
}

export interface WorkspaceFilterEndProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  children: ReactNode;
}

/** 첫 줄의 오른쪽 끝 — 검색과 상세 필터 토글이 사는 자리. */
export function WorkspaceFilterEnd({ children, className, ...props }: WorkspaceFilterEndProps) {
  return (
    <div {...props} className={joinClassNames("workspace-filter-end", className)}>
      {children}
    </div>
  );
}

export interface WorkspaceSearchProps {
  className?: string;
  isDisabled?: boolean;
  /** 접근 이름. 라벨은 시각적으로 숨기고 placeholder가 같은 문구를 보여 준다. */
  label: string;
  onChange: (value: string) => void;
  /**
   * Enter로 적용하는 화면만 넘긴다. 클라이언트 목록을 좁히는 화면은 `onChange`만으로
   * 즉시 반영하고 이 값을 비운다 — 적용 시점은 데이터 원천이 정한다.
   */
  onEnter?: () => void;
  placeholder?: string;
  value: string;
}

/**
 * 목록 검색 입력.
 *
 * `hasClear`라 값이 있을 때 지우기 단추가 생기고 그 단추가 라벨 이름을 품는다. 그래서
 * 테스트 locator는 `getByRole("textbox", { name })`만 쓴다(`getByLabel`은 strict mode
 * 위반이 된다).
 */
export function WorkspaceSearch({
  className,
  isDisabled = false,
  label,
  onChange,
  onEnter,
  placeholder,
  value,
}: WorkspaceSearchProps) {
  return (
    <TextInput
      className={joinClassNames("workspace-search", className)}
      data-review-primitive="text-input"
      hasClear
      isDisabled={isDisabled}
      isLabelHidden
      label={label}
      onChange={onChange}
      onEnter={onEnter}
      placeholder={placeholder ?? label}
      size="sm"
      startIcon={Search}
      value={value}
    />
  );
}

export interface WorkspaceAdvancedToggleProps {
  /**
   * 접힌 상세 필터 안에 걸려 있는 필터 수. 0보다 크면 버튼 옆에 수를 그린다.
   * 버튼의 접근 이름에는 섞지 않는다 — `getByRole("button", { name: "상세 필터" })`가
   * 수에 따라 깨지면 안 되기 때문이다.
   */
  activeCount?: number;
  className?: string;
  /** 열고 닫는 영역의 id. {@link WorkspaceFilterAdvanced}의 `id`와 같아야 한다. */
  controlsId: string;
  isOpen: boolean;
  label?: string;
  onToggle: () => void;
}

/**
 * 상세 필터 열기/닫기 토글.
 *
 * 아이콘 전용 버튼이며 `label`이 `aria-label`이 된다(Astryx `Button isIconOnly`).
 * `className`은 바깥 wrapper에 붙는다 — 활성 필터 수가 버튼 바로 옆에 붙어 있어야
 * 하므로 둘을 한 요소로 묶는다.
 */
export function WorkspaceAdvancedToggle({
  activeCount,
  className,
  controlsId,
  isOpen,
  label = "상세 필터",
  onToggle,
}: WorkspaceAdvancedToggleProps) {
  const showCount = activeCount !== undefined && activeCount > 0;
  return (
    <span className={joinClassNames("workspace-advanced-toggle", className)}>
      <Button
        aria-controls={controlsId}
        aria-expanded={isOpen}
        icon={<ListFilter aria-hidden="true" />}
        isIconOnly
        label={label}
        onClick={onToggle}
        size="sm"
      />
      {showCount ? (
        <span aria-label={`활성 필터 ${formatCount(activeCount)}개`} className="workspace-filter-count">
          {formatCount(activeCount)}
        </span>
      ) : null}
    </span>
  );
}

export interface WorkspaceFilterContextProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  children: ReactNode;
}

/**
 * 필터 바의 둘째 줄 — 필터가 아니라 **지금 보고 있는 범위의 사실**을 적는 자리다.
 * 사전규격의 SW 중심 스위치와 범위 안내, Go/No-Go의 두 캡션이 여기 온다.
 * 서버가 거르지 못하는 필터(사전규격 `grade`)를 밝히는 문장도 이 줄에 둔다.
 */
export function WorkspaceFilterContext({ children, className, ...props }: WorkspaceFilterContextProps) {
  return (
    <div {...props} className={joinClassNames("workspace-filter-context", className)}>
      {children}
    </div>
  );
}

export interface WorkspaceFilterAdvancedProps extends Omit<HTMLAttributes<HTMLDivElement>, "children" | "id"> {
  children: ReactNode;
  /**
   * 열 수. `--workspace-advanced-columns`로 내려가 grid가
   * `repeat(n, minmax(0,1fr)) auto`가 된다(마지막 `auto`는 초기화 버튼 자리).
   * @default 2
   */
  columns?: number;
  /** {@link WorkspaceAdvancedToggle}의 `controlsId`와 같아야 한다. */
  id: string;
  onReset: () => void;
  /**
   * 초기화 버튼 라벨. 화면이 "기본값"이라고 부르는 상태로 되돌리는 경우
   * (사전규격의 SW 기본 보기) 그 뜻을 지키려고 라벨을 바꾼다.
   * @default "필터 초기화"
   */
  resetLabel?: string;
}

/**
 * 접혔다 펴지는 상세 필터 영역.
 *
 * 접혀 있어도 URL 동기화와 축의 AND/OR 의미는 그대로다 — 접는 것은 보이는 정도이지
 * 걸린 필터를 없애는 일이 아니다. 그래서 토글이 활성 필터 수를 옆에 그린다.
 * 초기화 버튼은 항상 마지막 자리(오른쪽 끝)에 있으므로 화면이 따로 그리지 않는다.
 *
 * 열 하나를 통째로 쓰는 자식(발주계획의 저장된 뷰)은 화면 CSS에서
 * `grid-column: 1 / -1`을 준다.
 */
export function WorkspaceFilterAdvanced({
  children,
  className,
  columns = 2,
  id,
  onReset,
  resetLabel = "필터 초기화",
  style,
  ...props
}: WorkspaceFilterAdvancedProps) {
  return (
    <div
      {...props}
      className={joinClassNames("workspace-filter-advanced", className)}
      id={id}
      style={{ ...style, "--workspace-advanced-columns": columns } as CSSProperties}
    >
      {children}
      <Button className="workspace-filter-reset" label={resetLabel} onClick={onReset} size="sm" />
    </div>
  );
}

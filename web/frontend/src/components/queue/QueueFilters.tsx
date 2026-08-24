import type { ChangeEvent } from "react";

export interface QueueFilterValues {
  grade: string;
  readiness: string;
  focus: string;
  sampleRole: string;
  attachment: "any" | "none" | "manual";
  q: string;
  sort: "deadline" | "grade" | "published";
}

interface QueueFiltersProps {
  value: QueueFilterValues;
  focusOptions: string[];
  onChange: <K extends keyof QueueFilterValues>(key: K, value: QueueFilterValues[K]) => void;
  total: number;
  reviewedCount: number;
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="queue-filter-select">
      <span>{label}</span>
      <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <path d="m6 9 6 6 6-6" />
      </svg>
    </label>
  );
}

export function QueueFilters({ value, focusOptions, onChange, total, reviewedCount }: QueueFiltersProps) {
  const onSearchChange = (event: ChangeEvent<HTMLInputElement>) => onChange("q", event.target.value);
  return (
    <div className="queue-filters" aria-label="검토 대기열 필터">
      <label className="queue-search">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-4-4" />
        </svg>
        <input
          aria-label="공고명·기관 검색"
          placeholder="공고명·기관 검색"
          type="search"
          value={value.q}
          onChange={onSearchChange}
        />
      </label>

      <FilterSelect
        label="등급"
        value={value.grade}
        onChange={(next) => onChange("grade", next)}
        options={[
          { value: "", label: "검토 대상 전체" },
          { value: "우선 검토", label: "우선 검토" },
          { value: "검토 권장", label: "검토 권장" },
          { value: "관찰 대상", label: "관찰 대상" },
          { value: "제외", label: "제외" },
        ]}
      />
      <FilterSelect
        label="준비 상태"
        value={value.readiness}
        onChange={(next) => onChange("readiness", next)}
        options={[
          { value: "", label: "전체" },
          { value: "부분 확인 필요", label: "부분 확인 필요" },
          { value: "참여 불가 확인", label: "참여 불가 확인" },
          { value: "확인 완료", label: "확인 완료" },
        ]}
      />
      <FilterSelect
        label="역량 축"
        value={value.focus}
        onChange={(next) => onChange("focus", next)}
        options={[
          { value: "", label: "전체" },
          ...focusOptions.map((focus) => ({ value: focus, label: focus })),
        ]}
      />
      <FilterSelect
        label="표본"
        value={value.sampleRole}
        onChange={(next) => onChange("sampleRole", next)}
        options={[
          { value: "analysis", label: "분석 표본" },
          { value: "audit", label: "감사 표본" },
          { value: "all", label: "전체 표본" },
        ]}
      />
      <FilterSelect
        label="첨부"
        value={value.attachment}
        onChange={(next) => onChange("attachment", next as QueueFilterValues["attachment"])}
        options={[
          { value: "any", label: "첨부 전체" },
          { value: "none", label: "미확보" },
          { value: "manual", label: "수동 확보" },
        ]}
      />

      <div className="queue-filter-summary">
        <span>미리뷰 <strong className="mono tabular-nums">{Math.max(total - reviewedCount, 0)}</strong>건</span>
        <FilterSelect
          label="정렬"
          value={value.sort}
          onChange={(next) => onChange("sort", next as QueueFilterValues["sort"])}
          options={[
            { value: "deadline", label: "마감 임박순" },
            { value: "grade", label: "등급순" },
            { value: "published", label: "공고일순" },
          ]}
        />
      </div>
    </div>
  );
}

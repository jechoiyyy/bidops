import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";

export function SourceVerificationSetting({ value, onChange, disabled = false }: { value: boolean; onChange: (value: boolean) => void; disabled?: boolean }) {
  return <CheckboxInput
    label="원문 인용·숫자 대조"
    value={value}
    onChange={onChange}
    isDisabled={disabled}
    description={value ? "원문과 인용·수치를 대조해요. 표기 차이는 허용하며, 새 분석에만 적용돼요." : "대조를 생략하고 보고서에 ‘원문 대조 미실시’를 표시해요. 출처 범위와 데이터 형식 검사는 유지해요."}
  />;
}

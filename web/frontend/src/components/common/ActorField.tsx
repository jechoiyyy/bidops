import { useId, type InputHTMLAttributes } from "react";

interface ActorFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "type" | "value"> {
  description?: string;
  label?: string;
  onChange: (value: string) => void;
  value: string;
}

/** Claimed actor는 감사 표식일 뿐 로그인·신원 인증·권한이 아니다. */
export function ActorField({
  description = "감사 귀속용 이름이며 로그인·신원 인증·권한 부여가 아닙니다.",
  id,
  label = "담당자 claimed name",
  maxLength = 128,
  onChange,
  value,
  ...inputProps
}: ActorFieldProps) {
  const generatedId = useId();
  const inputId = id ?? `actor-${generatedId}`;
  const descriptionId = `${inputId}-description`;

  return (
    <div className="actor-field">
      <label htmlFor={inputId}>{label}</label>
      <input
        {...inputProps}
        id={inputId}
        type="text"
        value={value}
        maxLength={maxLength}
        aria-describedby={descriptionId}
        onChange={(event) => onChange(event.target.value)}
      />
      <p id={descriptionId}>{description}</p>
    </div>
  );
}

import type { ReactNode } from "react";

interface DisabledReasonProps {
  children: ReactNode;
  className?: string;
  id: string;
}

/** 비활성 control의 aria-describedby가 가리키는 화면상 사유다. */
export function DisabledReason({ children, className = "", id }: DisabledReasonProps) {
  return <p className={`disabled-reason ${className}`.trim()} id={id}>{children}</p>;
}

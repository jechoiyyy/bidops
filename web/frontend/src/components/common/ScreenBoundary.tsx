import type { ReactNode } from "react";
import { Text } from "@astryxdesign/core";

export type ScreenBoundaryProps =
  | { variant?: "screen"; determines: string; doesNotDetermine: string; children?: never }
  | { variant: "decision"; children: ReactNode; determines?: never; doesNotDetermine?: never };

/** Place below the title, or beside the decision control with variant="decision". */
export function ScreenBoundary(props: ScreenBoundaryProps) {
  return (
    <Text as="p" display="block" color="secondary">
      {props.variant === "decision"
        ? props.children
        : `이 화면이 정하는 것: ${props.determines} · 정하지 않는 것: ${props.doesNotDetermine}`}
    </Text>
  );
}

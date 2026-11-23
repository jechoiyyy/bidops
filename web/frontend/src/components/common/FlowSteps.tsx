import type { ComponentProps, ReactNode } from "react";
import { Step, Stepper } from "@astryxdesign/core/Stepper";
import { Check, CircleDot, Minus } from "lucide-react";

interface FlowStep {
  label: string;
  description?: string;
  status?: ComponentProps<typeof Step>["status"];
  state?: "done" | "current" | "unknown" | "todo";
  action?: ReactNode;
}

const indicators = {
  done: <Check aria-hidden="true" />,
  current: <CircleDot aria-hidden="true" />,
  unknown: <Minus aria-hidden="true" />,
  todo: "number",
} as const;

export function FlowSteps({
  steps, active, vertical = false, label = "사업 흐름",
}: { steps: readonly FlowStep[]; active: number; vertical?: boolean; label?: string }) {
  const activeState = steps[active]?.state;
  // Stepper completes everything before activeStep. Set indicators explicitly
  // when a prior connection is still unknown or the sequence is non-linear.
  const linear = (activeState === undefined || activeState === "current")
    && steps.every((step, index) => step.state === undefined
      || step.state === (index < active ? "done" : index === active ? "current" : "todo"));
  return (
    <div className="workbench-flow">
      <Stepper activeStep={linear ? active : -1} orientation={vertical ? "vertical" : "horizontal"} density="compact" label={label}>
        {steps.map((step, index) => {
          const state = step.state ?? (index < active ? "done" : index === active ? "current" : "todo");
          const status = step.status ?? (linear ? undefined : state === "done" ? "success" : state === "current" ? "accent" : undefined);
          return (
            <Step
              {...(!linear && state === "current" ? { "aria-current": "step" } : {})}
              data-step-state={state}
              description={step.description}
              indicator={linear ? "auto" : indicators[state]}
              key={step.label}
              label={step.label}
              status={status}
              step={index}
            >
              {step.action}
            </Step>
          );
        })}
      </Stepper>
    </div>
  );
}

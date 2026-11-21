import { useLayoutEffect, useRef, type KeyboardEvent } from "react";
import { Dialog as AstryxDialog, type DialogProps } from "@astryxdesign/core/Dialog";

/** Keep Tab inside the native modal and return to its opener even when the caller unmounts it. */
export function Dialog({ isOpen, onKeyDown, ...props }: Omit<DialogProps, "ref">) {
  const surface = useRef<HTMLDialogElement>(null);
  useLayoutEffect(() => {
    if (!isOpen) return;
    const trigger = document.activeElement;
    const dialog = surface.current;
    return () => {
      requestAnimationFrame(() => {
        if (dialog?.isConnected && dialog.open) return;
        if (trigger instanceof HTMLElement && trigger.isConnected && trigger !== document.body) {
          if (!document.querySelector("dialog:modal") || trigger.closest("dialog:modal")) {
            trigger.focus({ preventScroll: true });
          }
        }
      });
    };
  }, [isOpen]);

  function cycleTab(event: KeyboardEvent<HTMLDialogElement>) {
    onKeyDown?.(event);
    if (event.key !== "Tab" || event.defaultPrevented) return;
    const dialog = event.currentTarget;
    if (!(event.target instanceof Element) || event.target.closest("dialog") !== dialog) return;
    const controls = Array.from(dialog.querySelectorAll<HTMLElement>(
      "button, input, select, textarea, a[href], summary, [tabindex]",
    )).filter((element) => element.tabIndex >= 0 && !element.matches(":disabled")
      && !element.closest("[inert]") && element.checkVisibility({ visibilityProperty: true }));
    const edge = event.shiftKey ? controls[0] : controls.at(-1);
    if (document.activeElement !== edge) return;
    event.preventDefault();
    (event.shiftKey ? controls.at(-1) : controls[0])?.focus();
  }

  return <AstryxDialog {...props} isOpen={isOpen} ref={surface} onKeyDown={cycleTab} />;
}

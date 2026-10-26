import { useCallback, useEffect, useRef } from "react";

/** Reveal once after React/async content mounts; never follow background updates. */
export function revealSection(id: string) {
  let stopped = false, frame = 0, timeout = 0, highlight = 0;
  let revealed: HTMLElement | null = null;
  const stopWaiting = () => {
    observer.disconnect(); window.clearTimeout(timeout);
    window.removeEventListener("wheel", cancel);
    window.removeEventListener("touchstart", cancel);
    window.removeEventListener("pointerdown", cancel);
    window.removeEventListener("keydown", cancel);
  };
  function cancel() {
    stopped = true; stopWaiting(); window.cancelAnimationFrame(frame);
    window.clearTimeout(highlight); revealed?.removeAttribute("data-workflow-reveal");
  }
  const attempt = () => {
    window.cancelAnimationFrame(frame);
    frame = window.requestAnimationFrame(() => {
      if (stopped) return;
      const target = document.getElementById(id);
      if (!target || target.closest('[hidden], [inert], [aria-hidden="true"], [data-workflow-ready="false"]')) return;
      // Do not scroll the page behind a confirmation/editor dialog.
      const modal = document.querySelector("dialog[open]");
      if (modal && !modal.contains(target)) return;
      if (getComputedStyle(target).display === "none") return;
      stopped = true; stopWaiting(); revealed = target;
      target.scrollIntoView?.({ behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start", inline: "nearest" });
      target.setAttribute("data-workflow-reveal", "true");
      highlight = window.setTimeout(() => target.removeAttribute("data-workflow-reveal"), 1800);
      // Leave keyboard focus in the composer/input; scrolling must not steal it.
    });
  };
  const observer = new MutationObserver(attempt);
  observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden", "inert", "open", "aria-hidden", "data-workflow-ready"] });
  for (const event of ["wheel", "touchstart", "pointerdown", "keydown"]) window.addEventListener(event, cancel, { passive: true });
  timeout = window.setTimeout(cancel, 8000);
  attempt();
  return cancel;
}

export function useSectionReveal() {
  const cancel = useRef<(() => void) | undefined>(undefined);
  useEffect(() => () => cancel.current?.(), []);
  return useCallback((id: string) => { cancel.current?.(); cancel.current = revealSection(id); }, []);
}

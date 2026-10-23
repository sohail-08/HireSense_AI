import { useEffect, useId, useRef, useState, type ReactNode } from "react";

// Keep panels mounted so tab changes cannot lose a draft, captions or analysis.
export function MeetingTabs({ label, tabs, fill = false, variant = "underline", pageScroll = false, activeId, onActiveChange }: { label: string; tabs: { id: string; label: string; content: ReactNode }[]; fill?: boolean; variant?: "underline" | "segmented"; pageScroll?: boolean; activeId?: string; onActiveChange?: (id: string) => void }) {
  const [internalActive, setInternalActive] = useState(tabs[0].id);
  const active = activeId ?? internalActive;
  const setActive = (id: string) => { setInternalActive(id); onActiveChange?.(id); };
  const uid = useId();
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const tablist = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!pageScroll || variant !== "segmented") return;
    const bar = tablist.current;
    if (!bar) return;
    const update = () => {
      const height = bar.getBoundingClientRect().height;
      if (height > 0) bar.parentElement?.style.setProperty("--meeting-primary-tabs-height", `${height}px`);
    };
    update();
    const observer = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(update);
    observer?.observe(bar);
    window.addEventListener("resize", update);
    return () => { observer?.disconnect(); window.removeEventListener("resize", update); bar.parentElement?.style.removeProperty("--meeting-primary-tabs-height"); };
  }, [pageScroll, variant]);
  useEffect(() => {
    if (pageScroll) return;
    const panel = document.getElementById(`${uid}-${active}-panel`);
    const log = panel?.querySelector<HTMLElement>('[role="log"]');
    if (log && !log.closest("[hidden]")) log.scrollTop = log.scrollHeight;
    const transcript = panel?.querySelector('[data-scroll-mode="panel"][data-has-lines="true"][data-auto-follow="true"]');
    const transcriptPanel = transcript?.closest<HTMLElement>('[role="tabpanel"]');
    if (transcriptPanel && !transcriptPanel.closest("[hidden]")) transcriptPanel.scrollTop = transcriptPanel.scrollHeight;
  }, [active, uid, pageScroll]);
  return <section className={`hiresense-meeting-tabs min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm ${fill ? "hiresense-meeting-tabs-fill" : ""} ${variant === "segmented" ? "hiresense-meeting-tabs-segmented" : ""} ${pageScroll ? "hiresense-meeting-tabs-page" : ""}`}>
    <div ref={tablist} role="tablist" aria-label={label} className="flex gap-1 overflow-x-auto border-b border-slate-100 px-3 pt-2">
      {tabs.map((tab, index) => <button key={tab.id} ref={element => { buttons.current[index] = element; }} type="button" role="tab"
        id={`${uid}-${tab.id}-tab`} aria-controls={`${uid}-${tab.id}-panel`} aria-selected={active === tab.id} tabIndex={active === tab.id ? 0 : -1}
        className={`shrink-0 border-b-2 px-4 py-3 text-sm font-semibold transition focus-visible:outline-2 focus-visible:outline-blue-600 ${active === tab.id ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}
        onClick={() => setActive(tab.id)} onKeyDown={event => {
          const next = event.key === "ArrowRight" ? (index + 1) % tabs.length : event.key === "ArrowLeft" ? (index - 1 + tabs.length) % tabs.length : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : undefined;
          if (next !== undefined) { event.preventDefault(); setActive(tabs[next].id); buttons.current[next]?.focus(); }
        }}>{tab.label}</button>)}
    </div>
    {tabs.map(tab => <div key={tab.id} role="tabpanel" tabIndex={0} id={`${uid}-${tab.id}-panel`} data-panel-id={tab.id} aria-labelledby={`${uid}-${tab.id}-tab`} hidden={active !== tab.id} className="hiresense-meeting-panel min-w-0 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-200">{tab.content}</div>)}
  </section>;
}

import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";

type Job = { id: number; title: string; application_count: number };
type Props = { jobs: Job[]; value?: number; loading: boolean; onChange: (id: number) => void };

function countLabel(count: number) { return `${count} ${count === 1 ? "candidate" : "candidates"}`; }

export function JobPostingSelect({ jobs, value, loading, onChange }: Props) {
  const uid = useId();
  const listId = `${uid}-jobs`;
  const labelId = `${uid}-label`;
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const search = useRef({ text: "", time: 0 });
  const [open, setOpen] = useState(false);
  const [activeId, setActiveId] = useState<number>();
  const [position, setPosition] = useState<CSSProperties>({});
  const selected = jobs.find(job => job.id === value);
  const disabled = loading || !jobs.length;
  const expanded = open && !disabled;
  const activeIndex = Math.max(0, jobs.findIndex(job => job.id === activeId));
  const optionId = (id: number) => `${listId}-${id}`;

  function show(index = Math.max(0, jobs.findIndex(job => job.id === value))) {
    if (disabled) return;
    setActiveId(jobs[index]?.id); setOpen(true);
  }
  function choose(job: Job) {
    setOpen(false); search.current.text = "";
    if (job.id !== value) onChange(job.id);
    // The ranking panel remounts on job change. Focus its replacement trigger.
    window.requestAnimationFrame(() => {
      const replacement = document.getElementById("screening-job");
      if (replacement?.dataset.jobId === String(job.id)) replacement.focus();
    });
  }

  useLayoutEffect(() => {
    if (!expanded) return;
    function place() {
      const rect = trigger.current?.getBoundingClientRect();
      if (!rect) return;
      const width = Math.min(Math.max(rect.width, 300), window.innerWidth - 24);
      const below = window.innerHeight - rect.bottom - 20;
      const above = rect.top - 20;
      const flip = below < 200 && above > below;
      setPosition({ position: "fixed", width, left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)),
        maxHeight: Math.max(0, Math.min(320, flip ? above : below)),
        ...(flip ? { bottom: window.innerHeight - rect.top + 8 } : { top: rect.bottom + 8 }) });
    }
    function outside(event: Event) {
      const target = event.target as Node;
      if (!trigger.current?.contains(target) && !menu.current?.contains(target)) { setOpen(false); search.current.text = ""; }
    }
    place();
    document.addEventListener("pointerdown", outside);
    document.addEventListener("focusin", outside);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("focusin", outside);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [expanded]);

  useEffect(() => {
    if (expanded && activeId !== undefined) document.getElementById(optionId(activeId))?.scrollIntoView?.({ block: "nearest" });
  }, [expanded, activeId]);

  function keyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (disabled) return;
    if (["ArrowDown", "ArrowUp", "Home", "End", "Enter", " ", "Escape"].includes(event.key)) event.preventDefault();
    if (event.key === "Escape") { setOpen(false); search.current.text = ""; return; }
    if (event.key === "Tab") { setOpen(false); search.current.text = ""; return; }
    if (event.key === "Enter" || event.key === " ") {
      if (expanded && jobs[activeIndex]) choose(jobs[activeIndex]); else show();
    } else if (event.key === "Home" || event.key === "End") {
      show(event.key === "Home" ? 0 : jobs.length - 1);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!expanded) show();
      else setActiveId(jobs[(activeIndex + (event.key === "ArrowDown" ? 1 : -1) + jobs.length) % jobs.length].id);
    } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      const now = Date.now();
      search.current.text = (now - search.current.time < 700 ? search.current.text : "") + event.key.toLocaleLowerCase();
      search.current.time = now;
      const query = search.current.text;
      const index = jobs.findIndex(job => job.title.toLocaleLowerCase().startsWith(query));
      if (index >= 0) show(index);
    }
  }

  return <div>
    <label id={labelId} htmlFor="screening-job" className="block text-xs font-semibold text-slate-600">Job posting</label>
    <button id="screening-job" data-job-id={value} ref={trigger} type="button" role="combobox" aria-labelledby={labelId}
      aria-expanded={expanded} aria-haspopup="listbox" aria-controls={expanded ? listId : undefined}
      aria-activedescendant={expanded && jobs[activeIndex] ? optionId(jobs[activeIndex].id) : undefined}
      disabled={disabled} onClick={() => expanded ? setOpen(false) : show()} onKeyDown={keyDown}
      className={`mt-1.5 flex w-full items-center gap-3 rounded-xl border bg-white px-3 py-2.5 text-left shadow-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-200 disabled:opacity-60 ${expanded ? "border-blue-400 ring-2 ring-blue-100" : "border-slate-200 hover:border-blue-300 hover:bg-blue-50/30"}`}>
      <span aria-hidden="true" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600"><svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="3" y="7" width="18" height="14" rx="3" /><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12a23 23 0 0 0 18 0M12 11v4" /></svg></span>
      <span className="min-w-0 flex-1"><span className="block truncate text-sm font-semibold text-slate-800" title={selected?.title}>{selected?.title ?? (loading ? "Loading jobs…" : "No job postings available")}</span>
        {selected ? <span className="mt-0.5 block text-xs text-slate-500">Posting #{selected.id} · {countLabel(selected.application_count)}</span> : null}</span>
      <svg aria-hidden="true" className={`h-4 w-4 shrink-0 text-slate-400 transition-transform ${expanded ? "rotate-180 text-blue-600" : ""}`} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="m5 7.5 5 5 5-5" /></svg>
    </button>
    {expanded ? createPortal(<div id={listId} ref={menu} role="listbox" aria-labelledby={labelId} style={position}
      className="z-[70] overflow-y-auto overscroll-contain rounded-2xl border border-slate-200 bg-white p-1.5 shadow-xl shadow-slate-900/15">
      {jobs.map(job => <div key={job.id} id={optionId(job.id)} role="option" aria-selected={job.id === value}
        onPointerDown={event => event.preventDefault()} onPointerMove={() => setActiveId(job.id)} onClick={() => choose(job)}
        className={`flex cursor-pointer items-center justify-between gap-3 rounded-xl px-3 py-3 transition-colors ${job.id === activeId ? "bg-blue-50" : "hover:bg-slate-50"}`}>
        <div className="min-w-0"><p className={`break-words text-sm font-semibold ${job.id === value ? "text-blue-700" : "text-slate-800"}`}>{job.title}</p>
          <p className="mt-1 text-xs text-slate-500">Posting #{job.id} · {countLabel(job.application_count)}</p></div>
        {job.id === value ? <span aria-hidden="true" className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-600 text-white"><svg className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2"><path d="m5 10 3 3 7-7" /></svg></span> : null}
      </div>)}
    </div>, document.body) : null}
  </div>;
}

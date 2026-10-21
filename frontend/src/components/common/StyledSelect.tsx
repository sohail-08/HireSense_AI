import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";

export type SelectOption = { value: string; label: string; description?: string; disabled?: boolean };
type Base = { id?: string; label: string; options: SelectOption[]; disabled?: boolean; placeholder?: string;
  className?: string; compact?: boolean; icon?: ReactNode; minMenuWidth?: number };
type Single = Base & { multiple?: false; value: string; onChange: (value: string) => void };
type Multiple = Base & { multiple: true; value: string[]; onChange: (value: string[]) => void };

export function StyledSelect(props: Single | Multiple) {
  const uid = useId();
  const id = props.id ?? `${uid}-select`;
  const listId = `${uid}-options`;
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const search = useRef({ text: "", time: 0 });
  const [open, setOpen] = useState(false);
  const [activeValue, setActiveValue] = useState<string>();
  const [position, setPosition] = useState<CSSProperties>({});
  const selectedValues = props.multiple ? props.value : [props.value];
  const selected = props.options.find(option => selectedValues.includes(option.value));
  const enabled = props.options.filter(option => !option.disabled);
  const disabled = props.disabled || !enabled.length;
  const expanded = open && !disabled;
  const activeIndex = Math.max(0, enabled.findIndex(option => option.value === activeValue));
  const optionId = (value: string) => `${listId}-${props.options.findIndex(option => option.value === value)}`;
  const caption = props.multiple ? (props.value.length ? `${props.value.length} selected` : props.placeholder ?? "Choose options")
    : selected?.label ?? props.placeholder ?? "Choose an option";

  function close() { setOpen(false); search.current.text = ""; }
  function show(index = Math.max(0, enabled.findIndex(option => selectedValues.includes(option.value)))) {
    if (disabled || trigger.current?.matches(":disabled")) return;
    setActiveValue(enabled[index]?.value); setOpen(true);
  }
  function choose(option: SelectOption) {
    if (option.disabled || disabled || trigger.current?.matches(":disabled")) return;
    if (props.multiple) {
      props.onChange(props.value.includes(option.value) ? props.value.filter(value => value !== option.value) : [...props.value, option.value]);
      trigger.current?.focus();
    } else {
      close();
      if (props.value !== option.value) props.onChange(option.value);
      // Some job-scoped panels remount after selection. Restore their new trigger.
      window.requestAnimationFrame(() => {
        const replacement = document.getElementById(id);
        if (replacement?.dataset.selectedValue === option.value) replacement.focus();
      });
    }
  }

  useEffect(() => { if (disabled) close(); }, [disabled]);

  useLayoutEffect(() => {
    if (!expanded) return;
    function place() {
      const rect = trigger.current?.getBoundingClientRect();
      if (!rect) return;
      const width = Math.min(Math.max(rect.width, props.minMenuWidth ?? (props.compact ? 120 : 260)), window.innerWidth - 24);
      const below = window.innerHeight - rect.bottom - 20;
      const above = rect.top - 20;
      const flip = below < 200 && above > below;
      setPosition({ position: "fixed", width, left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)),
        maxHeight: Math.max(0, Math.min(320, flip ? above : below)),
        ...(flip ? { bottom: window.innerHeight - rect.top + 8 } : { top: rect.bottom + 8 }) });
    }
    function outside(event: Event) {
      const target = event.target as Node;
      if (!trigger.current?.contains(target) && !menu.current?.contains(target)) close();
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
  }, [expanded, props.compact, props.minMenuWidth]);

  useEffect(() => {
    if (expanded && activeValue !== undefined) document.getElementById(optionId(activeValue))?.scrollIntoView?.({ block: "nearest" });
  }, [expanded, activeValue]);

  function keyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (disabled) return;
    if (["ArrowDown", "ArrowUp", "Home", "End", "Enter", " ", "Escape"].includes(event.key)) event.preventDefault();
    if (event.key === "Escape" || event.key === "Tab") { close(); return; }
    if (event.key === "Enter" || event.key === " ") {
      if (expanded && enabled[activeIndex]) choose(enabled[activeIndex]); else show();
    } else if (event.key === "Home" || event.key === "End") {
      show(event.key === "Home" ? 0 : enabled.length - 1);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!expanded) show();
      else setActiveValue(enabled[(activeIndex + (event.key === "ArrowDown" ? 1 : -1) + enabled.length) % enabled.length].value);
    } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      const now = Date.now();
      search.current.text = (now - search.current.time < 700 ? search.current.text : "") + event.key.toLocaleLowerCase();
      search.current.time = now;
      const index = enabled.findIndex(option => option.label.toLocaleLowerCase().startsWith(search.current.text));
      if (index >= 0) show(index);
    }
  }

  return <>
    <button id={id} data-selected-value={props.multiple ? props.value.join(",") : props.value} ref={trigger} type="button" role="combobox" aria-label={props.label}
      aria-expanded={expanded} aria-haspopup="listbox" aria-controls={expanded ? listId : undefined}
      aria-activedescendant={expanded && enabled[activeIndex] ? optionId(enabled[activeIndex].value) : undefined}
      disabled={disabled} onClick={() => expanded ? close() : show()} onKeyDown={keyDown}
      className={`items-center gap-3 rounded-xl border bg-white text-left shadow-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-200 disabled:cursor-not-allowed disabled:opacity-60 ${props.compact ? "inline-flex min-w-16 px-2.5 py-1.5 text-xs" : "flex w-full px-3 py-2.5 text-sm"} ${expanded ? "border-blue-400 ring-2 ring-blue-100" : "border-slate-200 hover:border-blue-300 hover:bg-blue-50/30"} ${props.className ?? ""}`}>
      {props.icon}
      <span className="min-w-0 flex-1"><span className="block truncate font-medium text-slate-800" title={caption}>{caption}</span>
        {!props.multiple && selected?.description ? <span className="mt-0.5 block text-xs text-slate-500">{selected.description}</span> : null}</span>
      <svg aria-hidden="true" className={`h-4 w-4 shrink-0 text-slate-400 transition-transform ${expanded ? "rotate-180 text-blue-600" : ""}`} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="m5 7.5 5 5 5-5" /></svg>
    </button>
    {expanded ? createPortal(<div id={listId} ref={menu} role="listbox" aria-label={props.label} aria-multiselectable={props.multiple || undefined} style={position}
      className="z-[70] overflow-y-auto overscroll-contain rounded-2xl border border-slate-200 bg-white p-1.5 shadow-xl shadow-slate-900/15">
      {props.options.map(option => <div key={option.value} id={optionId(option.value)} role="option" aria-selected={selectedValues.includes(option.value)} aria-disabled={option.disabled || undefined}
        onPointerDown={event => event.preventDefault()} onPointerMove={() => { if (!option.disabled) setActiveValue(option.value); }} onClick={() => choose(option)}
        className={`flex items-center justify-between gap-3 rounded-xl px-3 transition-colors ${props.compact ? "py-2" : "py-3"} ${option.disabled ? "cursor-not-allowed opacity-45" : `cursor-pointer ${option.value === activeValue ? "bg-blue-50" : "hover:bg-slate-50"}`}`}>
        <div className="min-w-0"><p className={`break-words text-sm font-medium ${selectedValues.includes(option.value) ? "text-blue-700" : "text-slate-800"}`}>{option.label}</p>
          {option.description ? <p className="mt-1 text-xs text-slate-500">{option.description}</p> : null}</div>
        <span aria-hidden="true" className={`flex h-5 w-5 shrink-0 items-center justify-center ${props.multiple ? "rounded-md border" : "rounded-full"} ${selectedValues.includes(option.value) ? "border-blue-600 bg-blue-600 text-white" : "border-slate-300 text-transparent"}`}><svg className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2"><path d="m5 10 3 3 7-7" /></svg></span>
      </div>)}
    </div>, trigger.current?.closest("dialog") ?? document.body) : null}
  </>;
}

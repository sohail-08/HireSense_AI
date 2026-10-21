import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import { StyledSelect } from "./StyledSelect";

const dayMs = 86400000;
function dateAt(year: number, month: number, day: number) {
  const date = new Date(0); date.setUTCFullYear(year, month, day); date.setUTCHours(0, 0, 0, 0); return date;
}
function iso(date: Date) { return `${String(date.getUTCFullYear()).padStart(4, "0")}-${String(date.getUTCMonth() + 1).padStart(2, "0")}-${String(date.getUTCDate()).padStart(2, "0")}`; }
function parse(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return undefined;
  const [year, month, day] = value.split("-").map(Number);
  const date = dateAt(year, month - 1, day);
  return year > 0 && iso(date) === value ? date : undefined;
}
function today() {
  const parts = new Intl.DateTimeFormat("en", { timeZone: "Asia/Dhaka", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const part = (name: string) => parts.find(item => item.type === name)?.value ?? "";
  return parse(`${part("year")}-${part("month")}-${part("day")}`)!;
}
function dateLabel(date: Date) { return new Intl.DateTimeFormat("en-US", { timeZone: "UTC", month: "long", day: "numeric", year: "numeric" }).format(date); }
function shiftMonth(date: Date, offset: number) {
  const first = dateAt(date.getUTCFullYear(), date.getUTCMonth() + offset, 1);
  const last = dateAt(first.getUTCFullYear(), first.getUTCMonth() + 1, 0).getUTCDate();
  return dateAt(first.getUTCFullYear(), first.getUTCMonth(), Math.min(date.getUTCDate(), last));
}
function timeParts(value: string) {
  const valid = /^([01]\d|2[0-3]):[0-5]\d$/.test(value);
  const hour = valid ? Number(value.slice(0, 2)) : 8;
  return { hour: String(hour % 12 || 12).padStart(2, "0"), minute: valid ? value.slice(3) : "00", period: hour >= 12 ? "PM" : "AM" };
}
function timeLabel(value: string) { const parts = timeParts(value); return `${parts.hour}:${parts.minute} ${parts.period}`; }

const actionStyle = "rounded-lg px-3 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-blue-500";
const inputStyle = "mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100";

function PickerPopup({ title, trigger, onClose, children }: { title: string; trigger: RefObject<HTMLButtonElement | null>; onClose: () => void; children: ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useId();
  const [position, setPosition] = useState<CSSProperties>({});
  useLayoutEffect(() => {
    const element = dialog.current;
    element?.showModal();
    function place() {
      const anchor = trigger.current?.getBoundingClientRect();
      if (!anchor || !element) return;
      const width = Math.min(380, window.innerWidth - 24);
      const height = Math.min(element.getBoundingClientRect().height, window.innerHeight - 24);
      const below = anchor.bottom + 8;
      const top = below + height <= window.innerHeight - 12 ? below : Math.max(12, anchor.top - height - 8);
      setPosition({ width, left: Math.max(12, Math.min(anchor.left, window.innerWidth - width - 12)), top, right: "auto", bottom: "auto" });
    }
    place(); window.addEventListener("resize", place); window.addEventListener("scroll", place, true);
    const observer = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(place);
    if (element) observer?.observe(element);
    return () => { observer?.disconnect(); window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); element?.close(); if (trigger.current?.isConnected) trigger.current.focus(); };
  }, [trigger]);
  return createPortal(<dialog ref={dialog} aria-modal="true" aria-labelledby={heading} style={position}
    onCancel={event => { event.preventDefault(); onClose(); }} onClick={event => { if (event.target === event.currentTarget) onClose(); }}
    className="fixed m-0 max-h-[calc(100dvh-24px)] overflow-visible rounded-2xl border border-slate-200 bg-white p-0 text-slate-900 shadow-2xl shadow-slate-900/15 backdrop:bg-slate-900/15">
    <div className="max-h-[calc(100dvh-26px)] overflow-y-auto rounded-2xl p-4">
      <header className="mb-3 flex items-center justify-between gap-3"><h2 id={heading} className="font-semibold">{title}</h2>
        <button type="button" aria-label="Close picker" onClick={onClose} className="rounded-lg px-2 py-1 text-xl leading-6 text-slate-500 hover:bg-slate-100">×</button></header>
      {children}
    </div>
  </dialog>, document.body);
}

function Calendar({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const currentDay = iso(today());
  const initial = parse(value) ?? parse(currentDay)!;
  const [view, setView] = useState(initial);
  const [focused, setFocused] = useState(iso(initial));
  const [draft, setDraft] = useState(value);
  const uid = useId();
  const first = dateAt(view.getUTCFullYear(), view.getUTCMonth(), 1);
  const start = first.getTime() - first.getUTCDay() * dayMs;
  const dates = Array.from({ length: 42 }, (_, index) => new Date(start + index * dayMs));
  const heading = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", month: "long", year: "numeric" }).format(view);
  function moveMonth(offset: number) {
    const next = shiftMonth(view, offset); setView(next); setFocused(iso(dateAt(next.getUTCFullYear(), next.getUTCMonth(), 1)));
  }
  function keyDown(event: KeyboardEvent<HTMLButtonElement>, date: Date) {
    let next: Date | undefined;
    const offsets: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
    if (event.key in offsets) next = new Date(date.getTime() + offsets[event.key] * dayMs);
    if (event.key === "Home") next = new Date(date.getTime() - date.getUTCDay() * dayMs);
    if (event.key === "End") next = new Date(date.getTime() + (6 - date.getUTCDay()) * dayMs);
    if (event.key === "PageUp" || event.key === "PageDown") next = shiftMonth(date, event.key === "PageUp" ? -1 : 1);
    if (!next || next.getUTCFullYear() < 1 || next.getUTCFullYear() > 9999) return;
    event.preventDefault(); setView(next); setFocused(iso(next));
    const target = `${uid}-${iso(next)}`;
    window.requestAnimationFrame(() => document.getElementById(target)?.focus());
  }
  return <>
    <div className="mb-2 flex items-center justify-between rounded-xl bg-slate-50 p-1">
      <button type="button" aria-label="Previous month" disabled={view.getUTCFullYear() === 1 && view.getUTCMonth() === 0} onClick={() => moveMonth(-1)} className={actionStyle}>‹</button>
      <p aria-live="polite" className="text-sm font-semibold">{heading}</p>
      <button type="button" aria-label="Next month" disabled={view.getUTCFullYear() === 9999 && view.getUTCMonth() === 11} onClick={() => moveMonth(1)} className={actionStyle}>›</button>
    </div>
    <table role="grid" aria-label={heading} className="w-full table-fixed text-center text-sm">
      <thead><tr>{["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"].map(day => <th key={day} scope="col" className="py-2 text-xs font-medium text-slate-400">{day}</th>)}</tr></thead>
      <tbody>{Array.from({ length: 6 }, (_, row) => <tr key={row}>{dates.slice(row * 7, row * 7 + 7).map(date => {
        const key = iso(date); const selected = key === value; const isToday = key === currentDay;
        return <td key={key} className="p-0.5"><button id={`${uid}-${key}`} type="button" aria-label={dateLabel(date)} aria-pressed={selected} aria-current={isToday ? "date" : undefined}
          tabIndex={key === focused ? 0 : -1} autoFocus={key === focused} onKeyDown={event => keyDown(event, date)} onFocus={() => setFocused(key)} onClick={() => onChange(key)}
          disabled={date.getUTCFullYear() < 1 || date.getUTCFullYear() > 9999}
          className={`h-9 w-full rounded-lg font-medium transition focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-blue-500 ${selected ? "bg-blue-600 text-white shadow-sm" : `${date.getUTCMonth() === view.getUTCMonth() ? "text-slate-700" : "text-slate-300"} hover:bg-blue-50 hover:text-blue-700 ${isToday ? "ring-1 ring-inset ring-blue-300" : ""}`}`}>{date.getUTCDate()}</button></td>;
      })}</tr>)}</tbody>
    </table>
    <div className="mt-3 border-t border-slate-100 pt-3"><label className="text-xs font-medium text-slate-500">Enter date (YYYY-MM-DD)<input type="text" value={draft} placeholder="YYYY-MM-DD" className={inputStyle} onChange={event => setDraft(event.target.value)} /></label>
      {draft && !parse(draft) ? <p role="alert" className="mt-1 text-xs text-red-700">Enter a valid date as YYYY-MM-DD.</p> : null}
      <div className="mt-2 flex items-center justify-between gap-2"><div><button type="button" onClick={() => onChange(iso(today()))} className={actionStyle}>Today</button><button type="button" onClick={() => onChange("")} className={actionStyle}>Clear</button></div>
        <button type="button" disabled={!parse(draft)} onClick={() => onChange(draft)} className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-40">Use date</button></div>
    </div>
  </>;
}

function TimeChoices({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const initial = timeParts(value);
  const [hour, setHour] = useState(initial.hour); const [minute, setMinute] = useState(initial.minute); const [period, setPeriod] = useState(initial.period);
  const raw = `${String(Number(hour) % 12 + (period === "PM" ? 12 : 0)).padStart(2, "0")}:${minute}`;
  return <>
    <div className="mb-4 rounded-xl bg-blue-50 p-4 text-center"><p className="text-2xl font-bold tracking-wide text-blue-700">{timeLabel(raw)}</p><p className="mt-1 text-xs text-slate-500">Asia/Dhaka</p></div>
    <div className="grid grid-cols-3 gap-3">
      <label className="text-xs font-medium text-slate-500">Hour<StyledSelect label="Hour" className="mt-1" compact value={hour} options={Array.from({ length: 12 }, (_, index) => { const value = String(index + 1).padStart(2, "0"); return { value, label: value }; })} onChange={setHour} /></label>
      <label className="text-xs font-medium text-slate-500">Minute<StyledSelect label="Minute" className="mt-1" compact value={minute} options={Array.from({ length: 60 }, (_, index) => { const value = String(index).padStart(2, "0"); return { value, label: value }; })} onChange={setMinute} /></label>
      <label className="text-xs font-medium text-slate-500">AM / PM<StyledSelect label="AM / PM" className="mt-1" compact value={period} options={["AM", "PM"].map(value => ({ value, label: value }))} onChange={setPeriod} /></label>
    </div>
    <div className="mt-5 flex justify-between border-t border-slate-100 pt-3"><button type="button" onClick={() => onChange("")} className={actionStyle}>Clear</button><button type="button" onClick={() => onChange(raw)} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700">Use time</button></div>
  </>;
}

export function DateTimePicker({ label, kind, value, onChange, disabled }: { label: string; kind: "date" | "time"; value: string; onChange: (value: string) => void; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);
  const trigger = useRef<HTMLButtonElement>(null);
  const parsed = parse(value);
  const caption = value ? (kind === "date" ? parsed ? dateLabel(parsed) : "Choose date" : timeLabel(value)) : kind === "date" ? "Choose date" : "Choose time";
  return <div><span className="text-sm">{label}</span><button ref={trigger} type="button" aria-label={label} aria-haspopup="dialog" aria-expanded={open} disabled={disabled} onClick={() => setOpen(true)}
    className="mt-1 flex w-full items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-left text-sm shadow-sm transition hover:border-blue-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-200 disabled:opacity-50">
    <span className={value ? "font-medium text-slate-800" : "text-slate-400"}>{caption}</span>
    <svg aria-hidden="true" className="h-4 w-4 shrink-0 text-blue-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">{kind === "date" ? <><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4M17 3v4M3 11h18"/></> : <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>}</svg>
  </button>{open && !disabled ? <PickerPopup title={kind === "date" ? "Choose interview date" : "Choose start time"} trigger={trigger} onClose={() => setOpen(false)}>
    {kind === "date" ? <Calendar value={value} onChange={next => { onChange(next); setOpen(false); }} /> : <TimeChoices value={value} onChange={next => { onChange(next); setOpen(false); }} />}
  </PickerPopup> : null}</div>;
}

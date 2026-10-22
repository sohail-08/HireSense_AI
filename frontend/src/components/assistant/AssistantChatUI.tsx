import { useEffect, useRef, type ReactNode, type RefObject } from "react";

export const assistantChatStyles = {
  header: "shrink-0 border-b border-slate-200 bg-white px-4 py-3",
  conversation: "min-h-0 space-y-4 overflow-y-auto overscroll-contain bg-slate-50/70 px-4 py-4",
};

export function AssistantIdentity({ subtitle }: { subtitle: string }) {
  return <>
    <div aria-hidden="true" className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white shadow-sm">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="size-5"><path d="M8 10h8M8 14h5" strokeLinecap="round" /><path d="M6.5 19.5 3 21l1.1-3.8A8.5 8.5 0 1 1 6.5 19.5Z" strokeLinejoin="round" /></svg>
    </div>
    <div className="min-w-0 flex-1"><div className="flex items-center gap-2"><h2 className="truncate font-semibold text-slate-900">HireSense assistant</h2><span aria-hidden="true" className="size-2 shrink-0 rounded-full bg-emerald-500" /></div><p className="mt-0.5 truncate text-xs font-medium text-blue-700">{subtitle}</p></div>
  </>;
}

export function AssistantBubble({ role, outcome, children, label }: {
  role: "user" | "assistant"; outcome?: "success" | "failure"; children: ReactNode; label?: string;
}) {
  return <div data-chat-role={role} className={`flex min-w-0 ${role === "user" ? "justify-end" : "justify-start"}`}>
    <div role={label ? "article" : undefined} aria-label={label} className={`min-w-0 whitespace-pre-wrap break-words rounded-2xl px-4 py-3 text-sm leading-6 shadow-sm ${role === "user"
      ? "max-w-[88%] rounded-br-md bg-blue-600 text-white"
      : outcome === "success" ? "max-w-full rounded-bl-md border border-emerald-200 bg-emerald-50 text-emerald-900"
      : outcome === "failure" ? "max-w-full rounded-bl-md border border-red-200 bg-red-50 text-red-900"
      : "max-w-full rounded-bl-md border border-slate-200 bg-white text-slate-700"}`}>{children}</div>
  </div>;
}

export function AssistantWorking() {
  return <div className="flex justify-start" role="status"><div className="flex items-center gap-1.5 rounded-2xl rounded-bl-md border border-slate-200 bg-white px-4 py-3 shadow-sm">
    {["", "[animation-delay:150ms]", "[animation-delay:300ms]"].map((delay, index) => <span aria-hidden="true" key={index} className={`size-1.5 animate-pulse rounded-full bg-blue-500 motion-reduce:animate-none ${delay}`} />)}
    <span className="ml-2 text-xs text-slate-500">Working</span>
  </div></div>;
}

export function AssistantComposer({ id, label, value, placeholder, busy, onChange, onSend, maxLength, inputRef, active = true, className = "", children }: {
  id: string; label: string; value: string; placeholder: string; busy: boolean;
  onChange: (value: string) => void; onSend: () => void; maxLength?: number;
  inputRef?: RefObject<HTMLTextAreaElement | null>; active?: boolean; className?: string; children?: ReactNode;
}) {
  const ownRef = useRef<HTMLTextAreaElement>(null);
  const ref = inputRef ?? ownRef;
  useEffect(() => {
    const input = ref.current;
    if (!input || !active) return;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 112)}px`;
  }, [value, active, ref]);
  function send() { if (!busy && value.trim()) onSend(); }
  return <form onSubmit={event => { event.preventDefault(); send(); }} className={`shrink-0 border-t border-slate-200 bg-white p-3 ${className}`}>
    {children}<label htmlFor={id} className="sr-only">{label}</label>
    <div className="flex items-end gap-2 rounded-2xl border border-slate-300 bg-white p-2 shadow-sm transition focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-100">
      <textarea ref={ref} id={id} value={value} onChange={event => onChange(event.target.value)}
        onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(); } }}
        placeholder={placeholder} disabled={busy} rows={1} maxLength={maxLength}
        className="max-h-28 min-h-11 min-w-0 flex-1 resize-none overflow-y-auto border-0 bg-transparent px-2 py-2 text-sm leading-5 outline-none placeholder:text-slate-400 disabled:text-slate-400" />
      <button type="submit" disabled={busy || !value.trim()} className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300" aria-label="Send message">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" className="size-5"><path d="m5 12 14-7-4 14-3-6-7-1Z" strokeLinejoin="round" /></svg>
      </button>
    </div>
    <p className="supervisor-input-hint mt-1.5 text-center text-[11px] text-slate-400">Enter to send · Shift + Enter for a new line</p>
  </form>;
}

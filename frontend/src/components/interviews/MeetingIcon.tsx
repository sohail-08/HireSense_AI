export function MeetingIcon({ name, className = "h-5 w-5", slashed = false }: {
  name: "camera" | "microphone" | "screen" | "leave" | "person" | "lock" | "swap"; className?: string; slashed?: boolean;
}) {
  return <svg aria-hidden="true" className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    {name === "camera" ? <><rect x="3" y="5" width="13" height="14" rx="3"/><path d="m16 10 5-3v10l-5-3"/></> : null}
    {name === "microphone" ? <><rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/></> : null}
    {name === "screen" ? <><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4M12 13V7m-3 3 3-3 3 3"/></> : null}
    {name === "leave" ? <path d="M3 15c-1-1 2-7 9-7s10 6 9 7l-3 2-3-2v-3H9v3l-3 2Z"/> : null}
    {name === "person" ? <><circle cx="12" cy="8" r="4"/><path d="M4 22v-2a8 8 0 0 1 16 0v2"/></> : null}
    {name === "lock" ? <><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4M12 14v3"/></> : null}
    {name === "swap" ? <><path d="M4 8h15m-4-4 4 4-4 4M20 16H5m4-4-4 4 4 4"/></> : null}
    {slashed ? <path d="M3 3 21 21" /> : null}
  </svg>;
}

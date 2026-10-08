import {
  FormEvent,
  KeyboardEvent,
  useEffect,
  useRef,
} from "react";

import type { JobDescriptionEvidence } from "../../types";

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  outcome?: "success" | "failure";
};

type SupervisorChatPanelProps = {
  open: boolean;
  phaseLabel: string;
  messages: ChatMessage[];
  loading: boolean;
  input: string;
  placeholder: string;
  requirementContextVisible: boolean;
  requirementSources: JobDescriptionEvidence[];
  missingFields: string[];
  onOpen: () => void;
  onClose: () => void;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onNewSession: () => void;
};

export function SupervisorChatPanel({
  open,
  phaseLabel,
  messages,
  loading,
  input,
  placeholder,
  requirementContextVisible,
  requirementSources,
  missingFields,
  onOpen,
  onClose,
  onInputChange,
  onSend,
  onNewSession,
}: SupervisorChatPanelProps) {
  const messageListRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!open) return;

    function closeOnEscape(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }

    document.addEventListener("keydown", closeOnEscape);
    inputRef.current?.focus();
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose, open]);

  useEffect(() => {
    document.body.classList.toggle("supervisor-panel-open", open);
    return () => document.body.classList.remove("supervisor-panel-open");
  }, [open]);

  useEffect(() => {
    const navbar = document.querySelector<HTMLElement>(".interviewer-navbar");
    if (!navbar) return;

    const updateNavbarHeight = () => {
      document.documentElement.style.setProperty(
        "--interviewer-navbar-height",
        `${navbar.getBoundingClientRect().height}px`,
      );
    };
    const observer = new ResizeObserver(updateNavbarHeight);
    updateNavbarHeight();
    observer.observe(navbar);

    return () => {
      observer.disconnect();
      document.documentElement.style.removeProperty(
        "--interviewer-navbar-height",
      );
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    messageListRef.current?.scrollTo({
      top: messageListRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [loading, messages, open]);

  useEffect(() => {
    const textarea = inputRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 112)}px`;
  }, [input, open]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSend();
  }

  function handleInputKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (input.trim() && !loading) onSend();
    }
  }

  return (
    <>
      {!open ? (
        <button
          type="button"
          onClick={onOpen}
          aria-controls="supervisor-chat-panel"
          aria-expanded="false"
          className="fixed bottom-5 right-5 z-30 inline-flex items-center gap-2.5 rounded-full bg-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-blue-900/20 transition hover:-translate-y-0.5 hover:bg-blue-700 hover:shadow-xl focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 sm:bottom-6 sm:right-6"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            aria-hidden="true"
            className="size-5"
          >
            <path d="M8 10h8M8 14h5" strokeLinecap="round" />
            <path d="M6.5 19.5 3 21l1.1-3.8A8.5 8.5 0 1 1 6.5 19.5Z" strokeLinejoin="round" />
          </svg>
          Assistant
        </button>
      ) : null}

      <div
        className={`fixed inset-0 z-40 bg-slate-950/25 backdrop-blur-[1px] transition-opacity duration-200 lg:hidden ${
          open ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
        onClick={onClose}
        aria-hidden="true"
      />

      <aside
        id="supervisor-chat-panel"
        role="dialog"
        aria-modal="true"
        aria-label="HireSense supervisor"
        aria-hidden={!open}
        inert={!open}
        className={`supervisor-chat-panel fixed inset-y-0 right-0 z-50 flex w-full max-w-[440px] flex-col overflow-hidden border-l border-slate-200 bg-white shadow-2xl transition-transform duration-300 ease-out ${
          open ? "translate-x-0" : "pointer-events-none translate-x-full"
        }`}
      >
        <header className="shrink-0 border-b border-slate-200 bg-white px-4 py-3">
          <div className="flex items-center gap-2.5">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white shadow-sm">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                aria-hidden="true"
                className="size-5"
              >
                <path d="M8 10h8M8 14h5" strokeLinecap="round" />
                <path d="M6.5 19.5 3 21l1.1-3.8A8.5 8.5 0 1 1 6.5 19.5Z" strokeLinejoin="round" />
              </svg>
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <h2 className="truncate font-semibold text-slate-900">
                  HireSense assistant
                </h2>
                <span className="size-2 shrink-0 rounded-full bg-emerald-500" />
              </div>
              <p className="mt-0.5 truncate text-xs font-medium text-blue-700">
                {phaseLabel}
              </p>
            </div>
            <button
              type="button"
              onClick={onNewSession}
              disabled={loading}
              className="shrink-0 rounded-lg px-2 py-1.5 text-xs font-semibold text-blue-700 transition hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-blue-600 disabled:opacity-50"
            >
              New workflow
            </button>
            <button
              type="button"
              onClick={onClose}
              className="flex size-9 shrink-0 items-center justify-center rounded-lg text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 focus-visible:outline-2 focus-visible:outline-blue-600"
              aria-label="Close assistant"
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                aria-hidden="true"
                className="size-5"
              >
                <path d="m6 6 12 12M18 6 6 18" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        </header>

        <div
          ref={messageListRef}
          className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain bg-slate-50/70 px-4 py-4"
          aria-live="polite"
        >
          {messages.map((message, index) => (
            <div
              key={`${message.role}-${index}`}
              className={`flex ${
                message.role === "user" ? "justify-end" : "justify-start"
              }`}
            >
              <div
                className={`whitespace-pre-wrap break-words rounded-2xl px-4 py-3 text-sm leading-6 shadow-sm ${
                  message.role === "user"
                    ? "max-w-[88%] rounded-br-md bg-blue-600 text-white"
                    : message.outcome === "success"
                      ? "max-w-full rounded-bl-md border border-emerald-200 bg-emerald-50 text-emerald-900"
                      : message.outcome === "failure"
                        ? "max-w-full rounded-bl-md border border-red-200 bg-red-50 text-red-900"
                        : "max-w-full rounded-bl-md border border-slate-200 bg-white text-slate-700"
                }`}
              >
                <p>{message.content}</p>
              </div>
            </div>
          ))}

          {loading ? (
            <div className="flex justify-start" role="status">
              <div className="flex items-center gap-1.5 rounded-2xl rounded-bl-md border border-slate-200 bg-white px-4 py-3 shadow-sm">
                <span className="size-1.5 animate-pulse rounded-full bg-blue-500" />
                <span className="size-1.5 animate-pulse rounded-full bg-blue-500 [animation-delay:150ms]" />
                <span className="size-1.5 animate-pulse rounded-full bg-blue-500 [animation-delay:300ms]" />
                <span className="ml-2 text-xs text-slate-500">Working</span>
              </div>
            </div>
          ) : null}
          {requirementContextVisible && requirementSources.length ? (
            <details className="rounded-xl border border-blue-100 bg-blue-50/70 px-3 py-2.5 text-xs">
              <summary className="cursor-pointer font-semibold text-blue-700">
                {requirementSources.length} previous JD source
                {requirementSources.length === 1 ? "" : "s"} used
              </summary>
              <ul className="mt-2 space-y-1.5 text-slate-600">
                {requirementSources.map((source) => (
                  <li key={`${source.document_id}-${source.chunk_id}`}>
                    {source.document_title} · relevance {source.score.toFixed(2)}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}

          {requirementContextVisible && missingFields.length ? (
            <p className="rounded-xl border border-amber-100 bg-amber-50 px-3 py-2.5 text-xs text-amber-800">
              Still needed: {missingFields.join(", ")}.
            </p>
          ) : null}
        </div>

        <form onSubmit={submit} className="shrink-0 border-t border-slate-200 bg-white p-3">
          <label htmlFor="supervisor-message" className="sr-only">
            Message HireSense assistant
          </label>
          <div className="flex items-end gap-2 rounded-2xl border border-slate-300 bg-white p-2 shadow-sm transition focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-100">
            <textarea
              ref={inputRef}
              id="supervisor-message"
              value={input}
              onChange={(event) => onInputChange(event.target.value)}
              onKeyDown={handleInputKeyDown}
              placeholder={placeholder}
              disabled={loading}
              rows={1}
              className="max-h-28 min-h-11 min-w-0 flex-1 resize-none overflow-y-auto border-0 bg-transparent px-2 py-2 text-sm leading-5 outline-none placeholder:text-slate-400 disabled:text-slate-400"
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
              aria-label="Send message"
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                aria-hidden="true"
                className="size-5"
              >
                <path d="m5 12 14-7-4 14-3-6-7-1Z" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
          <p className="supervisor-input-hint mt-1.5 text-center text-[11px] text-slate-400">
            Enter to send · Shift + Enter for a new line
          </p>
        </form>
      </aside>
    </>
  );
}

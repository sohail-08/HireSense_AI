import {
  useEffect,
  useRef,
} from "react";

import { Link } from "react-router-dom";
import { AssistantBubble, AssistantComposer, AssistantIdentity, AssistantWorking, assistantChatStyles } from "../assistant/AssistantChatUI";

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
  assessmentLinks?: { label: string; path: string }[];
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
  assessmentLinks = [],
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
        className={`fixed inset-0 z-40 cursor-pointer bg-slate-950/25 backdrop-blur-[1px] transition-opacity duration-200 lg:hidden ${
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
        <header className={assistantChatStyles.header}>
          <div className="flex items-center gap-2.5">
            <AssistantIdentity subtitle={phaseLabel} />
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
          className={`flex-1 ${assistantChatStyles.conversation}`}
          aria-live="polite"
        >
          {messages.map((message, index) => (
            <AssistantBubble key={`${message.role}-${index}`} role={message.role} outcome={message.outcome}><p>{message.content}</p></AssistantBubble>
          ))}
          {assessmentLinks.map(link => <Link key={link.path} to={link.path} className="block rounded-xl border border-blue-200 bg-white p-3 text-sm font-semibold text-blue-700">{link.label}</Link>)}

          {loading ? <AssistantWorking /> : null}
        </div>

        <AssistantComposer id="supervisor-message" label="Message HireSense assistant" value={input} placeholder={placeholder} busy={loading} onChange={onInputChange} onSend={onSend} inputRef={inputRef} active={open} />
      </aside>
    </>
  );
}

import {
  createContext, useCallback, useContext, useEffect, useRef, useState,
  type ReactNode,
} from "react";
import { useLocation } from "react-router-dom";

import { ApiError, apiRequest } from "../../api/apiClient";
import { SupervisorChatPanel } from "../jobs/SupervisorChatPanel";
import type { ScreeningBatch, SupervisorChatResponse, SupervisorPhase } from "../../types";

const sessionKey = "hiresense_supervisor_session_id";
const initialMessage = "Tell me the role you want to hire for, or ask me to sync responses, screen candidates, schedule interviews, or reschedule an interview.";
type ChatMessage = { role: "user" | "assistant"; content: string; outcome?: "success" | "failure" };
type AssistantContext = {
  response: SupervisorChatResponse | undefined;
  loading: boolean;
  open: boolean;
  setOpen: (value: boolean) => void;
  sendMessage: (message: string) => Promise<void>;
  addTaskMessage: (outcome: "success" | "failure", content: string) => void;
  setSelectedJobDescriptionId: (id: number | undefined) => void;
  setSelectedJobPostingId: (id: number | undefined) => void;
  setSelectedApplicationIds: (ids: number[]) => void;
  refreshVersion: number;
  batch: ScreeningBatch | undefined;
};
const Context = createContext<AssistantContext | null>(null);

const phaseLabels: Record<SupervisorPhase, string> = {
  requirements: "Requirement discovery",
  requirement_confirmation: "Confirm requirements",
  requirement_confirmed: "Ready to generate JD",
  job_description_draft: "JD review",
  job_description_approved: "Ready to post",
  posting_details: "Posting details",
  posting_approval: "Confirm publication",
  published: "Published",
  error: "Needs attention",
  interview_selection: "Choose interview candidates", interview_schedule: "Interview schedule",
  interview_approval: "Confirm invitations", interview_sent: "Invitation delivery", interview_reschedule: "Reschedule interviews",
};

export function useSupervisor() {
  const value = useContext(Context);
  if (!value) throw new Error("SupervisorProvider is required");
  return value;
}

export function SupervisorProvider({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const page = pathname.endsWith("/candidates") ? "candidates"
    : pathname.endsWith("/interviews") ? "interviews"
    : pathname.endsWith("/assessments") ? "assessments"
      : pathname.endsWith("/jobs") ? "jobs" : "other";
  const [open, setOpen] = useState(() => window.matchMedia("(min-width: 1024px)").matches);
  const [response, setResponse] = useState<SupervisorChatResponse>();
  const [messages, setMessages] = useState<ChatMessage[]>([{ role: "assistant", content: initialMessage }]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [batch, setBatch] = useState<ScreeningBatch>();
  const [selectedJobDescriptionId, setSelectedJobDescriptionId] = useState<number>();
  const [selectedJobPostingId, setSelectedJobPostingId] = useState<number>();
  const [selectedApplicationIds, setSelectedApplicationIds] = useState<number[]>([]);
  const sessionId = useRef<string | undefined>(undefined);
  const busy = useRef(false);
  const close = useCallback(() => setOpen(false), []);

  const addTaskMessage = useCallback((outcome: "success" | "failure", content: string) => {
    setMessages((current) => [...current, { role: "assistant", outcome, content }]);
  }, []);

  const applyResponse = useCallback((value: SupervisorChatResponse) => {
    sessionId.current = value.session_id;
    sessionStorage.setItem(sessionKey, value.session_id);
    setResponse(value);
    setSelectedJobDescriptionId(value.job_description?.id);
    setMessages(value.messages.map((message) => ({
      ...message, outcome: message.outcome === "info" ? undefined : message.outcome,
    })));
    if (value.screening_batch) setBatch(value.screening_batch);
    if (value.refresh_required) setRefreshVersion((current) => current + 1);
  }, []);

  useEffect(() => {
    const saved = sessionStorage.getItem(sessionKey);
    if (!saved) return;
    sessionId.current = saved;
    let active = true;
    busy.current = true;
    setLoading(true);
    void apiRequest<SupervisorChatResponse>(`/supervisor/sessions/${saved}`)
      .then((value) => { if (active) applyResponse(value); })
      .catch((error) => {
        if (!active) return;
        if (error instanceof ApiError && error.status === 404) {
          sessionStorage.removeItem(sessionKey);
          sessionId.current = undefined;
        }
        else addTaskMessage("failure", error instanceof Error ? error.message : "Could not restore the assistant.");
      })
      .finally(() => { if (active) { busy.current = false; setLoading(false); } });
    return () => { active = false; };
  }, [applyResponse, addTaskMessage]);

  useEffect(() => {
    if (!batch || !["queued", "processing"].includes(batch.status)) return;
    let active = true;
    let polling = false;
    const timer = window.setInterval(() => {
      if (polling) return;
      polling = true;
      void apiRequest<ScreeningBatch>(`/screening/batches/${batch.id}`)
        .then((next) => {
          if (!active) return;
          setBatch(next);
          if (!["queued", "processing"].includes(next.status)) {
            window.clearInterval(timer);
            setRefreshVersion((current) => current + 1);
            addTaskMessage(next.status === "completed" ? "success" : "failure",
              `Screening batch #${next.id} ${next.status.replaceAll("_", " ")}: ${next.successful_applications} completed, ${next.failed_applications} failed. ${next.error_message ?? "Results and ranking have been refreshed. Requirements without accepted evidence receive zero credit."}`);
          }
        })
        .catch((error) => {
          if (!active) return;
          window.clearInterval(timer);
          addTaskMessage("failure", error instanceof Error ? error.message : "Could not load screening progress.");
        })
        .finally(() => { polling = false; });
    }, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [batch?.id, batch?.status, addTaskMessage]);

  useEffect(() => {
    const id = response?.interview_batch_id;
    if (!id) return;
    let active = true;
    let polling = false;
    const timer = window.setInterval(() => {
      if (polling) return;
      polling = true;
      void apiRequest<{ status: string; sent: number; failed: number; uncertain: number }>(`/interviews/batches/${id}`)
        .then((next) => {
          if (!active || next.status !== "completed") return;
          window.clearInterval(timer);
          setRefreshVersion((current) => current + 1);
          addTaskMessage(next.failed || next.uncertain ? "failure" : "success",
            `Interview invitations: ${next.sent} sent, ${next.failed} failed, ${next.uncertain} uncertain. Check Interviews for per-candidate results and safe retries.`);
        }).catch((error) => {
          if (!active) return;
          window.clearInterval(timer);
          addTaskMessage("failure", error instanceof Error ? error.message : "Could not read invitation delivery status.");
        }).finally(() => { polling = false; });
    }, 1500);
    return () => { active = false; window.clearInterval(timer); };
  }, [response?.interview_batch_id, addTaskMessage]);

  async function sendMessage(message: string) {
    const trimmed = message.trim();
    if (!trimmed || busy.current) return;
    busy.current = true;
    setLoading(true);
    setInput("");
    setMessages((current) => [...current, { role: "user", content: trimmed }]);
    try {
      applyResponse(await apiRequest<SupervisorChatResponse>("/supervisor/chat", {
        method: "POST",
        body: JSON.stringify({
          session_id: sessionId.current,
          message: trimmed,
          page_context: page,
          selected_job_description_id: page === "jobs" ? selectedJobDescriptionId ?? null : null,
          selected_job_posting_id: selectedJobPostingId ?? null,
          selected_application_ids: selectedApplicationIds,
        }),
      }));
    } catch (error) {
      addTaskMessage("failure", error instanceof Error ? error.message : "The task failed. Please try again.");
      setRefreshVersion((current) => current + 1);
    } finally {
      busy.current = false;
      setLoading(false);
    }
  }

  function newSession() {
    if (busy.current) return;
    sessionStorage.removeItem(sessionKey);
    sessionId.current = undefined;
    setResponse(undefined);
    setSelectedJobDescriptionId(undefined);
    setMessages([{ role: "assistant", content: initialMessage }]);
    setInput("");
  }

  const phase = response?.phase ?? "requirements";
  const requirement = response?.requirement_state;
  return (
    <Context.Provider value={{ response, loading, open, setOpen, sendMessage, addTaskMessage,
      setSelectedJobDescriptionId, setSelectedJobPostingId, setSelectedApplicationIds, refreshVersion, batch }}>
      {children}
      <SupervisorChatPanel
        open={open}
        phaseLabel={batch && ["queued", "processing"].includes(batch.status)
          ? `Screening ${batch.processed_applications}/${batch.total_applications}`
          : phase.startsWith("interview_") ? phaseLabels[phase]
          : page === "candidates" ? "Candidate collection" : page === "assessments" ? "CV screening and ranking" : phaseLabels[phase]}
        messages={messages}
        loading={loading}
        input={input}
        placeholder={page === "candidates" ? "e.g. Sync responses…"
          : page === "assessments" ? "Screen candidates for a job…" : "Message HireSense assistant…"}
        requirementContextVisible={phase.startsWith("requirement")}
        requirementSources={requirement?.source_references ?? []}
        missingFields={requirement?.missing_fields ?? []}
        onOpen={() => setOpen(true)}
        onClose={close}
        onInputChange={setInput}
        onSend={() => void sendMessage(input)}
        onNewSession={newSession}
      />
    </Context.Provider>
  );
}

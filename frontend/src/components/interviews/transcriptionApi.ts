import { apiRequest } from "../../api/apiClient";
import { candidateRequest } from "./roomApi";

export type TranscriptionStatus = {
  enabled: boolean; notice: string; notice_version: "transcription-v1"; retention_days: number;
  consented: boolean; both_consented: boolean; status: "not_started" | "starting" | "active" | "stopping" | "completed" | "failed";
  session_id: string | null; worker_identity: string | null; connection_status: string; failure_code: string | null;
  started_at: string | null; can_start: boolean;
};
export type TranscriptLine = {
  id?: string; session_id: string; stream_id?: string; speaker: "INTERVIEWER" | "CANDIDATE";
  sequence?: number; text: string; start_offset_ms: number; end_offset_ms: number;
  start_at?: string; end_at?: string; kind?: "final" | "interim"; saved?: boolean;
};
export const transcriptionApi = {
  status: (id?: number) => id === undefined ? candidateRequest<TranscriptionStatus>("transcription/status")
    : apiRequest<TranscriptionStatus>(`/interview-rooms/${id}/transcription/status`),
  consent: (consent: boolean, id?: number) => {
    const data = { consent, notice_version: "transcription-v1" };
    return id === undefined ? candidateRequest<TranscriptionStatus>("transcription/consent", data)
      : apiRequest<TranscriptionStatus>(`/interview-rooms/${id}/transcription/consent`, { method: "POST", body: JSON.stringify(data) });
  },
  control: (id: number, action: "start" | "stop") => apiRequest<TranscriptionStatus>(`/interview-rooms/${id}/transcription/${action}`, { method: "POST" }),
  history: (id: number, cursor?: string) => apiRequest<{ segments: TranscriptLine[]; next_cursor: string | null }>(
    `/interview-rooms/${id}/transcript${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`),
};

export function transcriptTime(milliseconds: number) {
  const seconds = Math.floor(Math.max(0, milliseconds) / 1000);
  const two = (value: number) => String(value).padStart(2, "0");
  return seconds >= 3600 ? `${two(Math.floor(seconds / 3600))}:${two(Math.floor(seconds / 60) % 60)}:${two(seconds % 60)}`
    : `${two(Math.floor(seconds / 60))}:${two(seconds % 60)}`;
}

export function mergeFinals(previous: TranscriptLine[], incoming: TranscriptLine[], limit = 10000) {
  const lines = new Map(previous.filter(line => line.id).map(line => [line.id, line]));
  for (const line of incoming) if (line.id && line.text.trim()) lines.set(line.id, { ...line, kind: "final", saved: true });
  return [...lines.values()].sort((a, b) => (a.start_at || "").localeCompare(b.start_at || "") || a.start_offset_ms - b.start_offset_ms
    || (a.sequence || 0) - (b.sequence || 0)).slice(-limit);
}

export function trustedTranscriptEvent(value: unknown, sender: string, status?: TranscriptionStatus): value is TranscriptLine & { kind: "final" | "interim" } {
  if (!status?.consented || !status.both_consented || sender !== status.worker_identity || typeof value !== "object" || !value) return false;
  const line = value as Partial<TranscriptLine>;
  return line.session_id === status.session_id && (line.kind === "final" || line.kind === "interim")
    && (line.speaker === "INTERVIEWER" || line.speaker === "CANDIDATE") && typeof line.text === "string" && line.text.length <= 12000
    && typeof line.stream_id === "string" && /^[a-f0-9]{32}$/.test(line.stream_id)
    && Number.isSafeInteger(line.start_offset_ms) && Number.isSafeInteger(line.end_offset_ms)
    && line.start_offset_ms! >= 0 && line.end_offset_ms! >= line.start_offset_ms!
    && (line.kind !== "final" || (line.saved === true && typeof line.id === "string" && /^[a-f0-9]{64}$/.test(line.id)));
}

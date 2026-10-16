import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TranscriptionProvider, TranscriptionPanel, TranscriptReceiver } from "../../src/components/interviews/TranscriptionPanel";
import { mergeFinals, transcriptTime, trustedTranscriptEvent, type TranscriptionStatus } from "../../src/components/interviews/transcriptionApi";
import { transcriptionApi } from "../../src/components/interviews/transcriptionApi";

const room = vi.hoisted(() => ({ registerTextStreamHandler: vi.fn(), unregisterTextStreamHandler: vi.fn(), on: vi.fn(), off: vi.fn() }));
vi.mock("@livekit/components-react", () => ({ useRoomContext: () => room }));
vi.mock("../../src/components/interviews/transcriptionApi", async original => ({ ...await original<any>(), transcriptionApi: {
  status: vi.fn(), consent: vi.fn(), control: vi.fn(), history: vi.fn(),
} }));

const initial: TranscriptionStatus = { enabled: true, notice: "Audio is sent to Deepgram; final text is stored, not audio.", notice_version: "transcription-v1",
  retention_days: 30, consented: false, both_consented: false, status: "not_started", session_id: "session", worker_identity: "trusted-agent",
  connection_status: "stopped", failure_code: null, started_at: null, can_start: false };
const active: TranscriptionStatus = { ...initial, consented: true, both_consented: true, status: "active", connection_status: "transcribing" };
const line = { id: "a".repeat(64), session_id: "session", stream_id: "a".repeat(32), speaker: "CANDIDATE" as const,
  sequence: 1, text: "A final answer", start_offset_ms: 1200, end_offset_ms: 2200, kind: "final" as const, saved: true };

function show(candidate = false) {
  return render(<TranscriptionProvider interviewId={candidate ? undefined : 1}><TranscriptReceiver /><TranscriptionPanel /></TranscriptionProvider>);
}
async function receive(event: object, sender = "trusted-agent") {
  const handler = room.registerTextStreamHandler.mock.calls.at(-1)![1];
  await act(async () => { await handler({ async *[Symbol.asyncIterator]() { yield JSON.stringify(event); } }, { identity: sender }); });
}

beforeEach(() => {
  vi.mocked(transcriptionApi.status).mockResolvedValue(initial);
  vi.mocked(transcriptionApi.history).mockResolvedValue({ segments: [], next_cursor: null });
  room.registerTextStreamHandler.mockClear();
});

describe("transcription controls and captions", () => {
  it("requires explicit consent before enabling start", async () => {
    show();
    const checkbox = await screen.findByRole("checkbox");
    expect((screen.getByRole("button", { name: "Start transcription" }) as HTMLButtonElement).disabled).toBe(true);
    expect((checkbox as HTMLInputElement).checked).toBe(false);
    vi.mocked(transcriptionApi.consent).mockResolvedValue({ ...initial, consented: true, both_consented: true, can_start: true });
    fireEvent.click(checkbox);
    await waitFor(() => expect((screen.getByRole("button", { name: "Start transcription" }) as HTMLButtonElement).disabled).toBe(false));
    vi.mocked(transcriptionApi.control).mockResolvedValue(active);
    fireEvent.click(screen.getByRole("button", { name: "Start transcription" }));
    await screen.findByText("Transcription active");
    expect(transcriptionApi.control).toHaveBeenCalledWith(1, "start");
    vi.mocked(transcriptionApi.control).mockResolvedValue({ ...active, status: "stopping" });
    fireEvent.click(screen.getByRole("button", { name: "Stop transcription" }));
    await screen.findByText("Stopping and saving");
  });

  it("replaces interim revisions and deduplicates persisted finals", async () => {
    vi.mocked(transcriptionApi.status).mockResolvedValue(active);
    show();
    await screen.findByText("Transcription active");
    await receive({ ...line, kind: "interim", text: "First draft" });
    await receive({ ...line, kind: "interim", text: "Revised draft" });
    expect(screen.queryByText("First draft")).toBeNull();
    expect(screen.getByText("Revised draft").parentElement?.className).toContain("italic");
    await receive(line);
    await receive(line);
    expect(screen.getAllByText("A final answer")).toHaveLength(1);
    expect(screen.queryByText("Revised draft")).toBeNull();
    expect(screen.getByText("Candidate · 00:01 · Final")).toBeTruthy();
    await receive({ ...line, id: "b".repeat(64), speaker: "INTERVIEWER", text: "A question" });
    expect(screen.getByText("Interviewer · 00:01 · Final")).toBeTruthy();
    await receive({ ...line, text: "Spoofed" }, "candidate-name");
    expect(screen.queryByText("Spoofed")).toBeNull();
  });

  it("restores saved text after refresh but candidate never fetches history or gets controls", async () => {
    vi.mocked(transcriptionApi.status).mockResolvedValue(active);
    vi.mocked(transcriptionApi.history).mockResolvedValue({ segments: [line], next_cursor: null });
    const page = show();
    await screen.findByText("A final answer");
    page.unmount();
    vi.mocked(transcriptionApi.history).mockClear();
    show(true);
    await screen.findByText("Transcription active");
    expect(transcriptionApi.history).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Start transcription" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Stop transcription" })).toBeNull();
    expect(screen.queryByText("A final answer")).toBeNull();
  });

  it("preserves manual scroll position and follows when at bottom", async () => {
    vi.mocked(transcriptionApi.status).mockResolvedValue(active);
    show();
    await screen.findByText("Transcription active");
    const panel = screen.getByLabelText("Transcript segments");
    Object.defineProperties(panel, { scrollHeight: { configurable: true, value: 1000 }, clientHeight: { configurable: true, value: 200 } });
    panel.scrollTop = 0;
    fireEvent.scroll(panel);
    await receive(line);
    expect(panel.scrollTop).toBe(0);
    panel.scrollTop = 800;
    fireEvent.scroll(panel);
    await receive({ ...line, id: "c".repeat(64), text: "Followed" });
    expect(panel.scrollTop).toBe(1000);
  });

  it("shows reconnection and persistence failure without affecting the video", async () => {
    vi.mocked(transcriptionApi.status).mockResolvedValue({ ...active, connection_status: "reconnecting", failure_code: "persistence_unavailable" });
    show();
    await screen.findByText("reconnecting");
    expect(screen.getByRole("alert").textContent).toContain("Audio/video is unaffected");
  });
});

it("formats long timestamps and rejects spoofed or malformed stream messages", () => {
  expect(transcriptTime(3_661_000)).toBe("01:01:01");
  expect(transcriptTime(-1)).toBe("00:00");
  expect(mergeFinals([line], [line])).toHaveLength(1);
  expect(trustedTranscriptEvent(line, "trusted-agent", active)).toBe(true);
  expect(trustedTranscriptEvent(line, "other", active)).toBe(false);
  expect(trustedTranscriptEvent({ ...line, session_id: "other" }, "trusted-agent", active)).toBe(false);
  expect(trustedTranscriptEvent({ ...line, speaker: "Speaker 0" }, "trusted-agent", active)).toBe(false);
  expect(trustedTranscriptEvent(line, "trusted-agent", initial)).toBe(false);
});

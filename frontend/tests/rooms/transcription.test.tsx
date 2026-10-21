import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TranscriptionProvider, TranscriptionPanel, TranscriptReceiver } from "../../src/components/interviews/TranscriptionPanel";
import { mergeFinals, transcriptTime, trustedTranscriptEvent, verifyCaptionMessage, type TranscriptionStatus } from "../../src/components/interviews/transcriptionApi";
import { webcrypto } from "node:crypto";
import { TextDecoder, TextEncoder } from "node:util";
import { transcriptionApi } from "../../src/components/interviews/transcriptionApi";
import { MeetingTabs } from "../../src/components/interviews/MeetingTabs";

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

it("uses the bounded bottom pane for transcript scrolling and respects manual reading position", async () => {
  vi.mocked(transcriptionApi.status).mockResolvedValue(active);
  render(<TranscriptionProvider interviewId={1}><TranscriptReceiver /><MeetingTabs fill label="Transcript tools" tabs={[{ id: "transcript", label: "Live transcript", content: <TranscriptionPanel panelScroll /> }]} /></TranscriptionProvider>);
  await screen.findByText("Transcription active");
  const panel = screen.getByRole("tabpanel", { name: "Live transcript" });
  const segments = screen.getByLabelText("Transcript segments");
  expect(segments.getAttribute("data-scroll-mode")).toBe("panel");
  expect(segments.className).not.toContain("overflow-y-auto");
  Object.defineProperties(panel, { scrollHeight: { configurable: true, value: 1000 }, clientHeight: { configurable: true, value: 200 } });
  panel.scrollTop = 100; fireEvent.scroll(panel);
  await receive({ ...line, kind: "interim", text: "Reading previous text" });
  expect(panel.scrollTop).toBe(100);
  panel.scrollTop = 800; fireEvent.scroll(panel);
  await receive({ ...line, kind: "interim", text: "Follow live text again" });
  expect(panel.scrollTop).toBe(1000);
});

it("keeps consent controls at the top when saved transcript text exists but consent is not given", async () => {
  vi.mocked(transcriptionApi.history).mockResolvedValue({ segments: [line], next_cursor: null });
  render(<TranscriptionProvider interviewId={1}><MeetingTabs fill label="Transcript tools" tabs={[
    { id: "transcript", label: "Live transcript", content: <TranscriptionPanel panelScroll /> },
    { id: "analysis", label: "Analysis", content: <p>Analysis content</p> },
  ]} /></TranscriptionProvider>);
  await screen.findByText("A final answer");
  const panel = screen.getByRole("tabpanel", { name: "Live transcript" });
  Object.defineProperties(panel, { scrollHeight: { configurable: true, value: 1000 }, clientHeight: { configurable: true, value: 200 } });
  panel.scrollTop = 0;
  fireEvent.click(screen.getByRole("tab", { name: "Analysis" }));
  fireEvent.click(screen.getByRole("tab", { name: "Live transcript" }));
  expect(panel.scrollTop).toBe(0);
  expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(false);
  expect((screen.getByRole("button", { name: "Start transcription" }) as HTMLButtonElement).disabled).toBe(true);
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

async function signedCaption(value: object, key: CryptoKey) {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  const signature = await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, key, bytes);
  const encode = (value: Uint8Array) => btoa(String.fromCharCode(...value)).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
  return { v: 1, payload: encode(bytes), signature: encode(new Uint8Array(signature)) };
}

it("shows signed captions from a hidden worker during speech, without stopping or history reload", async () => {
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("TextEncoder", TextEncoder);
  vi.stubGlobal("TextDecoder", TextDecoder);
  try {
    const pair = await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true, ["sign", "verify"]);
    const key = await crypto.subtle.exportKey("jwk", pair.publicKey);
    const state = { ...active, caption_public_key: key };
    vi.mocked(transcriptionApi.status).mockResolvedValue(state);
    vi.mocked(transcriptionApi.control).mockClear();
    show();
    await screen.findByText("Transcription active");
    await receive(await signedCaption({ ...line, event_index: 1, kind: "interim", text: "Appears while talking" }, pair.privateKey), "");
    expect(screen.getByText("Appears while talking")).toBeTruthy();
    expect(screen.getByText("Candidate · 00:01 · Live draft")).toBeTruthy();
    await receive(await signedCaption({ ...line, event_index: 2 }, pair.privateKey), "");
    expect(screen.getByText("A final answer")).toBeTruthy();
    expect(screen.queryByText("Appears while talking")).toBeNull();
    expect(transcriptionApi.control).not.toHaveBeenCalled();
    expect(screen.getByText("Transcription active")).toBeTruthy();
    const forged = await signedCaption({ ...line, text: "Tampered", event_index: 3 }, pair.privateKey);
    forged.signature = "a".repeat(86);
    await receive(forged, "");
    expect(screen.queryByText("Tampered")).toBeNull();
    // An older interim cannot reappear after its final, even if verification finishes late.
    await receive(await signedCaption({ ...line, kind: "interim", text: "Late draft", event_index: 1 }, pair.privateKey), "");
    expect(screen.queryByText("Late draft")).toBeNull();
    expect(await verifyCaptionMessage(line, "", state)).toBeUndefined();
    expect(await verifyCaptionMessage(line, "trusted-agent", state)).toBeUndefined();
    expect(await verifyCaptionMessage(line, "", active)).toBeUndefined();
    const other = await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true, ["sign", "verify"]);
    expect(await verifyCaptionMessage(await signedCaption({ ...line, event_index: 3 }, other.privateKey), "", state)).toBeUndefined();
  } finally { vi.unstubAllGlobals(); }
});

it("verifies a caption produced by the actual Python signing implementation", async () => {
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("TextEncoder", TextEncoder);
  vi.stubGlobal("TextDecoder", TextDecoder);
  try {
    // Synthetic public-key/signature fixture generated by CaptionSigner. No
    // private key, production secret or real interview content is included.
    const publicKey = { kty: "EC", crv: "P-256", x: "3dbbU0JIGDIlsSdlWMhjj7PPQ8BcdB2DlzYKcAaB04U", y: "SVeT7bX9nv4c0RBuFNgDoPYbE3-X0Mf-e-DTZfPC2OI" };
    const envelope = { v: 1,
      payload: "eyJlbmRfb2Zmc2V0X21zIjoyMjAwLCJldmVudF9pbmRleCI6MSwiaWQiOiJhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhIiwia2luZCI6ImZpbmFsIiwic2F2ZWQiOnRydWUsInNlcXVlbmNlIjoxLCJzZXNzaW9uX2lkIjoic2Vzc2lvbiIsInNwZWFrZXIiOiJDQU5ESURBVEUiLCJzdGFydF9vZmZzZXRfbXMiOjEyMDAsInN0cmVhbV9pZCI6ImFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhIiwidGV4dCI6IlB5dGhvbiB3b3JrZXIgY2FwdGlvbiJ9",
      signature: "MpfF-CjfkPbkC0Z7hjhS1qlyYyZpdPrE1kegpQUOmMLBXoCdLxtovzkC-XIiqC9h2NNSjIZqv0HAklW-5SOPuQ" };
    const result = await verifyCaptionMessage(envelope, "", { ...active, caption_public_key: publicKey });
    expect(result?.text).toBe("Python worker caption");
    expect(result?.speaker).toBe("CANDIDATE");
    expect(await verifyCaptionMessage(envelope, "", { ...active, session_id: "different-session", caption_public_key: publicKey })).toBeUndefined();
  } finally { vi.unstubAllGlobals(); }
});

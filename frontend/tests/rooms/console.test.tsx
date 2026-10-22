import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { InterviewerConsolePage } from "../../src/pages/InterviewerConsolePage";
import { ApiError } from "../../src/api/apiClient";
import { getSdk } from "./setup";
import { readFileSync } from "node:fs";

const api = vi.hoisted(() => ({ status: vi.fn(), admit: vi.fn(), end: vi.fn(), interviewerMedia: vi.fn(), interviewerConnected: vi.fn(), interviewerLeave: vi.fn(), link: vi.fn(), revoke: vi.fn() }));
vi.mock("../../src/components/interviews/roomApi", async (original) => ({ ...await original<any>(), roomApi: api }));
vi.mock("../../src/components/interviews/InterviewCopilotPanel", () => ({ InterviewCopilotPanel: () => <aside>Private interview assistance</aside> }));
const info = { interview_id: 1, candidate_name: "Test Candidate", job_title: "Frontend Engineer", scheduled_start: "2030-10-14T02:00:00Z", scheduled_end: "2030-10-14T02:30:00Z", timezone: "Asia/Dhaka", room_status: "waiting", waiting: true, admitted: false, has_join_link: true, link_revoked: false, room_version: 1 };
function open() { render(<MemoryRouter initialEntries={["/interviews/1/console"]}><Routes><Route path="/interviews/:interviewId/console" element={<InterviewerConsolePage />} /></Routes></MemoryRouter>); }
beforeEach(() => {
  api.status.mockResolvedValue(info); api.admit.mockResolvedValue({ ...info, admitted: true, waiting: false, room_status: "ready" });
  api.end.mockResolvedValue({ ...info, admitted: true, waiting: false, room_status: "ended" });
  api.interviewerMedia.mockResolvedValue({ server_url: "wss://test-project.livekit.cloud", participant_token: "fake-media-only", role: "interviewer" });
  api.interviewerConnected.mockResolvedValue({ ...info, admitted: true, waiting: false, room_status: "active" });
});
test("console authorization failure does not expose candidate or room controls", async () => {
  api.status.mockRejectedValue(new ApiError("Forbidden", 403)); open();
  expect((await screen.findByRole("alert")).textContent).toContain("not authorized");
  expect(screen.queryByText("Test Candidate")).toBeNull(); expect(screen.queryByRole("button", { name: "Admit candidate" })).toBeNull();
  expect(screen.queryByText("Private interview assistance")).toBeNull();
});
test("shows a waiting candidate and admits them without joining media automatically", async () => {
  const user = userEvent.setup(); open();
  const header = (await screen.findByRole("heading", { name: "Interview console" })).closest("header")!;
  expect(within(header).getByRole("region", { name: "Candidate admission" })).toBeTruthy();
  expect(within(header).getByRole("link", { name: "Back to interviews" })).toBeTruthy();
  const candidateLink = within(header).getByLabelText("Candidate link options");
  expect(candidateLink.querySelector("span")?.textContent).toBe("Candidate link");
  expect(candidateLink.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  expect(candidateLink.textContent).not.toContain("⌄");
  const css = readFileSync("src/index.css", "utf8");
  expect(css).toMatch(/\.hiresense-console-link-options \{[^}]*display: flex; align-items: center/);
  expect(css).toContain(".hiresense-console-link-chevron { display: block; flex: 0 0 1rem; width: 1rem; height: 1rem; }");
  await user.click(await screen.findByRole("button", { name: "Admit candidate" }));
  await screen.findByText("Candidate admitted");
  expect(api.admit).toHaveBeenCalledWith(1); expect(api.interviewerMedia).not.toHaveBeenCalled();
});

test("device submission is visible and reveals the interviewer join button", async () => {
  const user = userEvent.setup(); open();
  await user.click(await screen.findByRole("button", { name: "Check devices" }));
  const ready = screen.getByRole("button", { name: "Devices ready" });
  for (let node: HTMLElement | null = ready; node; node = node.parentElement) {
    expect(getComputedStyle(node).display).not.toBe("none");
  }
  expect(getComputedStyle(document.querySelector('input[name="username"]')!).display).toBe("none");
  expect(screen.queryByRole("button", { name: "Join interview room" })).toBeNull();
  await user.click(ready);
  expect(await screen.findByRole("button", { name: "Join interview room" })).toBeTruthy();
  expect(api.interviewerMedia).not.toHaveBeenCalled();
});

test.each(["Configure LIVEKIT_CLOUD_URL.", "Add LIVEKIT_CLOUD_API_KEY and LIVEKIT_CLOUD_API_SECRET."])("unavailable media disables joining: %s", async (media_notice) => {
  api.status.mockResolvedValue({ ...info, media_notice });
  const user = userEvent.setup(); open();
  await screen.findByText(media_notice);
  await user.click(screen.getByRole("button", { name: "Check devices" }));
  await user.click(screen.getByRole("button", { name: "Devices ready" }));
  expect(screen.getByRole("button", { name: "Join interview room" }).hasAttribute("disabled")).toBe(true);
  expect(api.interviewerMedia).not.toHaveBeenCalled();
});

test("updating an old-origin link requires explicit confirmation", async () => {
  api.status.mockResolvedValue({ ...info, link_origin_outdated: true });
  api.link.mockResolvedValue({ join_url: "https://demo.trycloudflare.com/interview/join/fake-test-only" });
  const user = userEvent.setup(); open();
  await user.click(await screen.findByLabelText("Candidate link options"));
  await user.click(await screen.findByRole("button", { name: "Update candidate link" }));
  expect(screen.getByRole("dialog")).toBeTruthy(); expect(api.link).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Confirm" }));
  expect(api.link).toHaveBeenCalledWith(1, "/rotate");
});
test("groups candidate link actions in the header without creating or copying a link on menu open", async () => {
  api.link.mockResolvedValue({ join_url: "https://demo.trycloudflare.com/interview/join/fake-test-only" });
  const user = userEvent.setup(); open();
  await user.click(await screen.findByLabelText("Candidate link options"));
  expect(api.link).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Replace link" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Revoke link" })).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Copy candidate link" }));
  expect(api.link).toHaveBeenCalledWith(1, "");
});
test("ending requires a confirmation dialog and renders ended state", async () => {
  const user = userEvent.setup(); open();
  await user.click(await screen.findByRole("button", { name: "End interview for everyone" }));
  expect(document.querySelector("main")?.classList.contains("hiresense-console-review")).toBe(false);
  expect(screen.getByRole("dialog")).toBeTruthy(); expect(api.end).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Keep interview open" }));
  expect(api.end).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "End interview for everyone" }));
  await user.click(screen.getByRole("button", { name: "Confirm end interview" }));
  await screen.findByRole("heading", { name: "Interview ended" });
  expect(api.end).toHaveBeenCalledWith(1); expect(screen.queryByRole("button", { name: "Admit candidate" })).toBeNull();
  expect((screen.getByRole("button", { name: "End interview for everyone" }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.queryByRole("button", { name: "Join interview room" })).toBeNull();
  expect(document.querySelector("main")?.classList.contains("hiresense-console-review")).toBe(true);
  const groupTabs = screen.getByRole("tablist", { name: "Workspace panel" }).parentElement!;
  const innerTabs = screen.getByRole("tablist", { name: "Interview workspace" }).parentElement!;
  for (const tabs of [groupTabs, innerTabs]) {
    expect(tabs.classList.contains("hiresense-meeting-tabs-page")).toBe(true);
    expect(tabs.classList.contains("hiresense-meeting-tabs-fill")).toBe(false);
  }
});

test.each(["ended", "cancelled"])("opens %s interviews in document-scroll review mode", async room_status => {
  api.status.mockResolvedValue({ ...info, room_status }); open();
  await screen.findByRole("heading", { name: room_status === "ended" ? "Interview ended" : "Interview cancelled" });
  expect(document.querySelector("main")?.classList.contains("hiresense-console-review")).toBe(true);
  expect(document.querySelector(".hiresense-console-media-slot")).toBeNull();
  expect(api.interviewerMedia).not.toHaveBeenCalled();
});

test("keeps the media on the left while switching right-side workspace groups and analysis tabs", async () => {
  const user = userEvent.setup(); open();
  await user.click(await screen.findByRole("button", { name: "Check devices" }));
  await user.click(screen.getByRole("button", { name: "Devices ready" }));
  await user.click(screen.getByRole("button", { name: "Join interview room" }));
  const media = await screen.findByTestId("media-room");
  const tools = screen.getByRole("complementary", { name: "Interviewer workspace" });
  expect(tools.contains(media)).toBe(false);
  await user.click(within(tools).getByRole("tab", { name: "Candidate & assistant" }));
  expect(screen.getByRole("tabpanel", { name: "Candidate & assistant" })).toBeTruthy();
  expect(screen.queryByRole("tab", { name: "Live transcript" })).toBeNull();
  expect(screen.getByText("Private interview assistance").closest('[role="tabpanel"]')?.hasAttribute("hidden")).toBe(false);
  expect(screen.getByTestId("media-room")).toBe(media);
  await user.click(within(tools).getByRole("tab", { name: "Transcript & analysis" }));
  expect(screen.getByRole("tabpanel", { name: "Transcript & analysis" })).toBeTruthy();
  await user.click(screen.getByRole("tab", { name: "Answer analysis" }));
  expect(screen.getByTestId("media-room")).toBe(media);
  await user.click(screen.getByRole("tab", { name: "Live transcript" }));
  expect(screen.getByTestId("media-room")).toBe(media);
  expect(getSdk().room.screen).toBe(false);
  expect(api.interviewerConnected).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("button", { name: "Share screen", exact: true })).toBeNull();
});

test("bounds the full-height left meeting and switchable right tools to one viewport", () => {
  const css = readFileSync("src/index.css", "utf8");
  expect(css).toMatch(/\.hiresense-console \{[^}]*height: 100dvh;[^}]*overflow: hidden/);
  expect(css).toMatch(/\.hiresense-console-grid \{[^}]*grid-template-columns: minmax\(0, 1.7fr\) minmax\(22rem, 1fr\); grid-template-rows: minmax\(0, 1fr\)/);
  expect(css).toMatch(/\.hiresense-console-toolbar \{[^}]*display: flex;[^}]*align-items: flex-end/);
  expect(css).toMatch(/@media \(max-width: 899px\)[\s\S]*\.hiresense-console-header \{ grid-template-columns: minmax\(0, 1fr\)/);
  expect(css).toMatch(/\.hiresense-console \.hiresense-video-stage \{[^}]*flex: 1;[^}]*min-height: 0; height: auto/);
  expect(css).toMatch(/\.hiresense-meeting-tabs-fill > \.hiresense-meeting-panel:not\(\[hidden\]\) \{[^}]*overflow-y: auto/);
  expect(css).toContain('.hiresense-console-grid[data-closed="true"] { grid-template-columns: minmax(0, 1fr); }');
  expect(css).toMatch(/\.hiresense-console-tools > \.hiresense-meeting-tabs-segmented > \.hiresense-meeting-panel:not\(\[hidden\]\) \{ overflow: hidden/);
  expect(css).not.toContain("hiresense-console-primary");
  expect(css).toMatch(/\.hiresense-console-review \{ height: auto; min-height: 100dvh; overflow: visible;/);
  expect(css).toMatch(/\.hiresense-meeting-tabs-page > \[role="tablist"\] \{ position: sticky; top: var\(--meeting-primary-tabs-height, 3.25rem\)/);
  expect(css).toMatch(/\.hiresense-meeting-tabs-page\.hiresense-meeting-tabs-segmented > \[role="tablist"\] \{ top: 0;/);
});

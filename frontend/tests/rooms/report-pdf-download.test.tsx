import React from "react";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ReportPdfDownload } from "../../src/components/assessments/ReportPdfDownload";
import { assessmentApi } from "../../src/components/assessments/assessmentApi";

vi.mock("../../src/components/assessments/assessmentApi", () => ({ assessmentApi: { export: vi.fn(), artifact: vi.fn(), blob: vi.fn() } }));
const completed = { id: 5, status: "completed", format: "pdf" as const };
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(assessmentApi.export).mockResolvedValue(completed);
  vi.mocked(assessmentApi.blob).mockResolvedValue(new Blob(["synthetic PDF"], { type: "application/pdf" }));
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:synthetic-report") });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});
afterEach(() => vi.restoreAllMocks());

it("only prepares a PDF on click and downloads it automatically", async () => {
  render(<ReportPdfDownload id={12} />);
  expect(assessmentApi.export).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Download this report" }));
  await waitFor(() => expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1));
  expect(assessmentApi.export).toHaveBeenCalledWith(12, "pdf");
  expect(assessmentApi.blob).toHaveBeenCalledWith(5);
  const anchor = vi.mocked(HTMLAnchorElement.prototype.click).mock.instances[0] as HTMLAnchorElement;
  expect(anchor.download).toBe("hiresense-report-12.pdf");
  expect(anchor.href).toBe("blob:synthetic-report");
  expect(document.body.contains(anchor)).toBe(false);
  expect((screen.getByRole("button") as HTMLButtonElement).disabled).toBe(false);
});

it("waits for preparation, prevents duplicate requests, and downloads when ready", async () => {
  vi.useFakeTimers();
  vi.mocked(assessmentApi.export).mockResolvedValue({ ...completed, status: "queued" });
  vi.mocked(assessmentApi.artifact).mockResolvedValueOnce({ ...completed, status: "processing" }).mockResolvedValueOnce(completed);
  render(<ReportPdfDownload id={12} />);
  const button = screen.getByRole("button");
  await act(async () => { fireEvent.click(button); fireEvent.click(button); });
  expect(assessmentApi.export).toHaveBeenCalledTimes(1);
  expect((button as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByRole("status").textContent).toContain("download when it is ready");
  await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
  expect(assessmentApi.blob).not.toHaveBeenCalled();
  await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
  expect(assessmentApi.artifact).toHaveBeenCalledTimes(2);
  expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1);
  expect((button as HTMLButtonElement).disabled).toBe(false);
  await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:synthetic-report");
});

it("allows retry after a failed download without offering HTML", async () => {
  vi.mocked(assessmentApi.blob).mockRejectedValueOnce(new Error("synthetic failure"));
  render(<ReportPdfDownload id={12} />);
  fireEvent.click(screen.getByRole("button"));
  expect((await screen.findByRole("alert")).textContent).toContain("could not be downloaded");
  expect(screen.queryByText(/HTML|Print report/)).toBeNull();
  fireEvent.click(screen.getByRole("button"));
  await waitFor(() => expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1));
  expect(screen.queryByRole("alert")).toBeNull();
});

it("allows retry after a request or polling failure", async () => {
  vi.mocked(assessmentApi.export).mockRejectedValueOnce(new Error("synthetic failure"));
  render(<ReportPdfDownload id={12} />);
  fireEvent.click(screen.getByRole("button"));
  expect((await screen.findByRole("alert")).textContent).toContain("could not be prepared");
  vi.useFakeTimers();
  vi.mocked(assessmentApi.export).mockResolvedValue({ ...completed, status: "queued" });
  vi.mocked(assessmentApi.artifact).mockRejectedValueOnce(new Error("synthetic poll failure"));
  await act(async () => { fireEvent.click(screen.getByRole("button")); });
  await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
  expect(screen.getByRole("alert").textContent).toContain("Could not check the PDF status");
  expect((screen.getByRole("button") as HTMLButtonElement).disabled).toBe(false);
});

it("stops polling when candidate details are closed", async () => {
  vi.useFakeTimers();
  vi.mocked(assessmentApi.export).mockResolvedValue({ ...completed, status: "queued" });
  const { unmount } = render(<ReportPdfDownload id={12} />);
  await act(async () => { fireEvent.click(screen.getByRole("button")); });
  unmount();
  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
  expect(assessmentApi.artifact).not.toHaveBeenCalled();
  expect(assessmentApi.blob).not.toHaveBeenCalled();
});

it("does not trigger a download after the report is closed", async () => {
  let resolveBlob!: (blob: Blob) => void;
  vi.mocked(assessmentApi.blob).mockReturnValue(new Promise(resolve => { resolveBlob = resolve; }));
  const { unmount } = render(<ReportPdfDownload id={12} />);
  fireEvent.click(screen.getByRole("button"));
  await waitFor(() => expect(assessmentApi.blob).toHaveBeenCalled());
  unmount();
  await act(async () => { resolveBlob(new Blob(["synthetic PDF"])); });
  expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();
});

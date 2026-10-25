import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { CandidatePhoto } from "../../src/components/interviews/CandidatePhoto";
import { apiBlob } from "../../src/api/apiClient";

vi.mock("../../src/api/apiClient", () => ({ apiBlob: vi.fn() }));

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:private-photo") });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  vi.mocked(apiBlob).mockResolvedValue(new Blob(["sanitized image"], { type: "image/jpeg" }));
});

test("loads the private uploaded photo with the authenticated blob API", async () => {
  const view = render(<CandidatePhoto interviewId={12} name="Ada" />);
  const image = await screen.findByRole("img", { name: "Ada's uploaded application photo" });
  expect(image.getAttribute("src")).toBe("blob:private-photo");
  expect(apiBlob).toHaveBeenCalledWith("/interview-rooms/12/candidate-photo", { signal: expect.any(AbortSignal) });
  view.unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:private-photo");
});

test("uses the existing person icon if the upload is missing or cannot be opened", async () => {
  vi.mocked(apiBlob).mockRejectedValue(new Error("Photo unavailable"));
  const view = render(<CandidatePhoto interviewId={12} name="Ada" />);
  await waitFor(() => expect(apiBlob).toHaveBeenCalledOnce());
  expect(screen.queryByRole("img")).toBeNull();
  expect(view.container.querySelector("svg")).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
});

test("does not create an image URL after the panel is unmounted", async () => {
  let resolve!: (blob: Blob) => void;
  vi.mocked(apiBlob).mockReturnValue(new Promise(value => { resolve = value; }));
  const view = render(<CandidatePhoto interviewId={12} name="Ada" />);
  view.unmount();
  await act(async () => { resolve(new Blob(["late image"], { type: "image/jpeg" })); });
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});

test("never shows a previous candidate's photo after changing interviews", async () => {
  const view = render(<CandidatePhoto interviewId={12} name="Ada" />);
  await screen.findByRole("img");
  let resolve!: (blob: Blob) => void;
  vi.mocked(apiBlob).mockReturnValue(new Promise(value => { resolve = value; }));
  view.rerender(<CandidatePhoto interviewId={13} name="Nadia" />);
  expect(screen.queryByRole("img")).toBeNull();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:private-photo");
  await act(async () => { resolve(new Blob(["new image"], { type: "image/jpeg" })); });
  expect(await screen.findByRole("img", { name: "Nadia's uploaded application photo" })).toBeTruthy();
});

test("falls back to the icon when image decoding fails", async () => {
  const view = render(<CandidatePhoto interviewId={12} name="Ada" />);
  fireEvent.error(await screen.findByRole("img"));
  expect(screen.queryByRole("img")).toBeNull();
  expect(view.container.querySelector("svg")).toBeTruthy();
});

test("does not render non-image responses as candidate photos", async () => {
  vi.mocked(apiBlob).mockResolvedValue(new Blob(["private error"], { type: "text/html" }));
  render(<CandidatePhoto interviewId={12} name="Ada" />);
  await waitFor(() => expect(apiBlob).toHaveBeenCalledOnce());
  expect(screen.queryByRole("img")).toBeNull();
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});

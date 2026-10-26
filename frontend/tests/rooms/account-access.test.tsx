import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import App from "../../src/App";
import { AuthProvider } from "../../src/auth/AuthProvider";
import { apiRequest, EXPIRY_KEY, TOKEN_KEY } from "../../src/api/apiClient";

vi.mock("../../src/api/apiClient", () => ({ apiRequest: vi.fn(), API_URL: "/api", TOKEN_KEY: "hiresense_token", EXPIRY_KEY: "hiresense_token_expiry", AUTH_EXPIRED_EVENT: "hiresense:auth-expired", ApiError: class extends Error {} }));
vi.mock("../../src/pages/InterviewerDashboard", () => ({ InterviewerDashboard: () => <h1>Hiring dashboard</h1> }));
vi.mock("../../src/pages/CandidateInterviewPage", () => ({ CandidateInterviewPage: () => <h1>Join your interview</h1> }));
vi.mock("../../src/components/common/ApplicationNotifications", () => ({ ApplicationNotifications: () => null }));

const owner = { id: 1, role: "interviewer", name: "Test interviewer", email: "owner@example.test", is_active: true, created_at: "2026-10-01" };
const candidate = { ...owner, id: 2, role: "candidate" };
function open(path = "/login") { return render(<MemoryRouter initialEntries={[path]}><AuthProvider><App /></AuthProvider></MemoryRouter>); }
beforeEach(() => {
  sessionStorage.clear(); vi.clearAllMocks(); vi.mocked(apiRequest).mockReset();
  Object.defineProperty(window, "matchMedia", { configurable: true, value: vi.fn(() => ({ matches: false })) });
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
});

it.each(["/login", "/register", "/candidate", "/candidate/dashboard", "/candidate/interviews"])("shows interviewer sign-in instead of signup/account pages at %s", async path => {
  open(path);
  await screen.findByRole("heading", { name: "Interviewer sign in" });
  expect(screen.queryByText("Joining as a candidate?")).toBeNull();
  expect(screen.queryByText(/Open the private interview link from your invitation/)).toBeNull();
  expect(screen.queryByRole("link", { name: /Create an account|Sign up/ })).toBeNull();
  expect(screen.queryByRole("heading", { name: "Candidate dashboard" })).toBeNull();
  expect(apiRequest).not.toHaveBeenCalled();
});

it.each(["/interview/join/synthetic-private-link", "/interview/join"])("keeps link-based interview entry public at %s", async path => {
  open(path);
  expect(await screen.findByRole("heading", { name: "Join your interview" })).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "Interviewer sign in" })).toBeNull();
  expect(apiRequest).not.toHaveBeenCalled();
});

it("clears a legacy candidate token instead of restoring a candidate account", async () => {
  sessionStorage.setItem(TOKEN_KEY, "synthetic-legacy-token");
  sessionStorage.setItem(EXPIRY_KEY, String(Date.now() + 60000));
  vi.mocked(apiRequest).mockResolvedValue(candidate);
  open("/interviewer/jobs");
  await screen.findByRole("heading", { name: "Interviewer sign in" });
  expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
  expect(sessionStorage.getItem(EXPIRY_KEY)).toBeNull();
  expect(apiRequest).toHaveBeenCalledTimes(1);
  expect(apiRequest).toHaveBeenCalledWith("/auth/me");
});

it("keeps interviewer sign-in working without exposing registration", async () => {
  vi.mocked(apiRequest).mockImplementation(async path => path === "/auth/login" ? { access_token: "synthetic-owner-token", expires_in: 3600, token_type: "bearer" } : owner);
  open(); await screen.findByRole("heading", { name: "Interviewer sign in" });
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "owner@example.test" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "synthetic-password" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("heading", { name: "Hiring dashboard" })).toBeTruthy();
  expect(sessionStorage.getItem(TOKEN_KEY)).toBe("synthetic-owner-token");
  expect(apiRequest).not.toHaveBeenCalledWith("/auth/register", expect.anything());
});

it("does not retain a candidate token even if an older server returns one", async () => {
  vi.mocked(apiRequest).mockImplementation(async path => path === "/auth/login" ? { access_token: "synthetic-candidate-token", expires_in: 3600, token_type: "bearer" } : candidate);
  open(); await screen.findByRole("heading", { name: "Interviewer sign in" });
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "candidate@example.test" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "synthetic-password" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("private interview link"));
  expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
  expect(screen.queryByRole("heading", { name: "Hiring dashboard" })).toBeNull();
});

import React from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Navbar } from "../../src/components/common/Navbar";

const auth = vi.hoisted(() => ({ user: { role: "interviewer", name: "Synthetic User" }, logout: vi.fn() }));
vi.mock("../../src/auth/AuthProvider", () => ({ useAuth: () => auth }));
vi.mock("../../src/components/common/ApplicationNotifications", () => ({ ApplicationNotifications: () => null }));

beforeEach(() => { auth.user.role = "interviewer"; });

it("shows the requested interviewer navigation order with existing destinations", () => {
  render(<MemoryRouter initialEntries={["/interviewer/assessments"]}><Navbar /></MemoryRouter>);
  const nav = within(screen.getByRole("navigation", { name: "Main navigation" }));
  const links = nav.getAllByRole("link");
  expect(links.map(link => link.textContent)).toEqual(["Jobs", "Candidates", "CV Screening", "Schedule Interviews", "Interview", "Assessment"]);
  expect(links.map(link => link.getAttribute("href"))).toEqual([
    "/interviewer/jobs", "/interviewer/candidates", "/interviewer/assessments", "/interviewer/schedule-interviews", "/interviewer/interviews", "/interviewer/reports",
  ]);
  expect(nav.queryByRole("link", { name: "Dashboard" })).toBeNull();
  expect(nav.getByRole("link", { name: "CV Screening" }).getAttribute("aria-current")).toBe("page");
});

it("highlights Assessment at the existing reports URL", () => {
  render(<MemoryRouter initialEntries={["/interviewer/reports"]}><Navbar /></MemoryRouter>);
  const active = screen.getByRole("link", { name: "Assessment", exact: true });
  expect(active.getAttribute("aria-current")).toBe("page");
  expect(active.className).toContain("border-blue-200 bg-blue-50 text-blue-800");
  expect(screen.getByRole("link", { name: "Jobs", exact: true }).className).toContain("border-transparent");
});

it("does not expose account navigation for legacy candidate accounts", () => {
  auth.user.role = "candidate";
  render(<MemoryRouter initialEntries={["/candidate/dashboard"]}><Navbar /></MemoryRouter>);
  expect(screen.queryByRole("navigation")).toBeNull();
  expect(screen.queryByRole("link")).toBeNull();
});

import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { DiscordPostPreview } from "../../src/components/jobs/DiscordPostPreview";
import { DiscordJobPostPanel } from "../../src/components/jobs/DiscordJobPostPanel";
import { apiRequest } from "../../src/api/apiClient";
import type { DiscordJobPost, JobDescriptionResponse } from "../../src/types";

vi.mock("../../src/api/apiClient", () => ({ apiRequest: vi.fn(), ApiError: class extends Error {} }));

const job: JobDescriptionResponse = { id: 7, requirement_profile_id: 1, title: "Backend Engineer", status: "approved", version: 1,
  content: "# Backend Engineer\n\nNorthstar Digital is seeking a backend engineer.\n\n## Responsibilities\n- Build **secure APIs**\n- Test with `Pytest`",
  structured_content: { title: "Old title", summary: "Old summary", responsibilities: [], required_skills: [], preferred_skills: [], qualifications: [], selection_criteria: [], experience_requirement: "Not specified." },
  source_references: [], created_by_user_id: 1, created_at: "2026-10-22T01:00:00Z", updated_at: "2026-10-22T01:00:00Z" };
const post: DiscordJobPost = { id: 15, job_description_id: 7, platform: "discord", heading: "BJIT is Hiring!", application_url: "https://example.test/apply",
  application_deadline: "2026-11-06", contact_email: "sohail.sh.ahmed@gmail.com", location: "House-5/B, Road-2/E, Block-J, Baridhara, Dhaka 1212", additional_instructions: "Include your CV.", reviewed_content: job.content,
  discord_payload: { embeds: [{ title: job.title, description: job.content.replace("Northstar Digital", "BJIT") }] }, job_description_version: 1, status: "draft", external_post_id: null, external_server_id: null, external_channel_id: null, external_url: null,
  error_code: null, error_message: null, attempt_started_at: null, published_at: null, created_at: "2026-10-22T01:00:00Z", updated_at: "2026-10-22T01:00:00Z" };

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() { this.removeAttribute("open"); } });
  vi.spyOn(window, "confirm").mockReturnValue(true);
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/job-postings/discord/defaults?job_description_id=7") return { ...post, job_description_content: job.content.replace("Northstar Digital", "BJIT"), mcp_configured: true };
    if (path === "/job-postings/discord?job_description_id=7") return [post];
    if (path === "/job-postings/discord/preview" && options?.method === "POST") return { ...post, ...JSON.parse(options.body as string) };
    if (path === "/job-postings/15/publish" && options?.method === "POST") return { ...post, status: "published" };
    throw new Error(`Unexpected synthetic request: ${path}`);
  });
});

afterEach(() => vi.restoreAllMocks());

function mutations() {
  return vi.mocked(apiRequest).mock.calls.filter(([, options]) => options?.method === "POST");
}

async function readyPanel() {
  const preview = await screen.findByRole("article", { name: "Discord post preview" });
  await waitFor(() => expect((screen.getByRole("button", { name: "Publish to Discord" }) as HTMLButtonElement).disabled).toBe(false));
  return preview;
}

it("formats the post with a single role title, readable headings and real bullet lists", () => {
  render(<DiscordPostPreview heading={post.heading!} title={job.title} content={job.content} fields={[]} />);
  const preview = screen.getByRole("article", { name: "Discord post preview" });
  expect(within(preview).getByText("BJIT is Hiring!")).toBeTruthy();
  expect(within(preview).getAllByRole("heading", { name: "Backend Engineer" })).toHaveLength(1);
  expect(within(preview).getByRole("heading", { name: "Responsibilities" })).toBeTruthy();
  expect(within(preview).getAllByRole("listitem")).toHaveLength(2);
  expect(within(preview).getByText("secure APIs").tagName).toBe("STRONG");
  expect(preview.textContent).not.toContain("##");
  expect(preview.textContent).not.toContain("Old summary");
  expect(screen.queryByRole("region", { name: "Application details" })).toBeNull();
});

it("groups application details, uses a readable deadline and makes valid application links usable", () => {
  render(<DiscordPostPreview heading={post.heading!} title={job.title} content={job.content} fields={[
    ["Application link", post.application_url!], ["Application deadline", post.application_deadline!],
    ["Contact email", post.contact_email!], ["Additional application instructions", post.additional_instructions!],
  ]} />);
  const details = screen.getByRole("region", { name: "Application details" });
  expect(within(details).getByText("6 Nov 2026")).toBeTruthy();
  const link = within(details).getByRole("link", { name: post.application_url! });
  expect(link.getAttribute("href")).toBe(post.application_url);
  expect(link.getAttribute("rel")).toContain("noopener");
  expect(within(details).getByText("Include your CV.")).toBeTruthy();
});

it("escapes untrusted text and refuses executable application URLs", () => {
  const { container } = render(<DiscordPostPreview heading='<img src=x onerror=alert(1)>' title={job.title}
    content='<script>alert(1)</script>\n[click](javascript:alert(1))' fields={[["Application link", "javascript:alert(1)"]]} />);
  expect(container.querySelector("script, img, a")).toBeNull();
  expect(screen.getByRole("article").textContent).toContain("<script>");
});

it("renders the real posting panel without mutating or publishing on load", async () => {
  render(<DiscordJobPostPanel jobDescription={job} />);
  const preview = await screen.findByRole("article", { name: "Discord post preview" });
  expect(within(preview).getByRole("heading", { name: "Responsibilities" })).toBeTruthy();
  expect(preview.textContent).toContain("BJIT is seeking a backend engineer.");
  expect(preview.textContent).not.toContain("Northstar Digital");
  expect(within(preview).getByText("sohail.sh.ahmed@gmail.com")).toBeTruthy();
  expect(within(preview).getByText("House-5/B, Road-2/E, Block-J, Baridhara, Dhaka 1212")).toBeTruthy();
  expect(screen.queryByLabelText("Heading")).toBeNull();
  expect(screen.queryByLabelText("Contact email")).toBeNull();
  expect(screen.queryByLabelText("Location")).toBeNull();
  expect(screen.queryByRole("button", { name: "Save reviewed preview" })).toBeNull();
  expect(screen.queryByText("Save this preview after every edit before publishing.")).toBeNull();
  expect(screen.queryByText(/Preview #|JD v/)).toBeNull();
  expect(screen.queryByText("Job post published to Discord.")).toBeNull();
  expect(vi.mocked(apiRequest).mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
  await waitFor(() => expect((screen.getByRole("button", { name: "Publish to Discord" }) as HTMLButtonElement).disabled).toBe(false));
});

it("refreshes a legacy draft and publishes it through the same button", async () => {
  const original = vi.mocked(apiRequest).getMockImplementation()!;
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/job-postings/discord?job_description_id=7") return [{ ...post, heading: "Old heading", contact_email: null, location: null,
      discord_payload: { embeds: [{ description: job.content }] } }];
    return original(path, options);
  });
  render(<DiscordJobPostPanel jobDescription={job} />);
  const preview = await readyPanel();
  expect(preview.textContent).not.toContain("Northstar Digital");
  expect(mutations()).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Publish to Discord" }));
  await screen.findByText("Job post published to Discord.");
  expect(mutations().map(([path]) => path)).toEqual(["/job-postings/discord/preview", "/job-postings/15/publish"]);
});

it("saves the latest edited details before publishing without a separate save action", async () => {
  render(<DiscordJobPostPanel jobDescription={job} />);
  await readyPanel();
  fireEvent.change(screen.getByLabelText("Additional application instructions"), { target: { value: "Attach your CV and portfolio." } });
  expect(within(screen.getByRole("article")).getByText("Attach your CV and portfolio.")).toBeTruthy();
  expect(mutations()).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Publish to Discord" }));
  await screen.findByText("Job post published to Discord.");
  expect(screen.queryByText("Publication history")).toBeNull();
  expect(screen.queryByText("published")).toBeNull();
  expect(mutations().map(([path]) => path)).toEqual(["/job-postings/discord/preview", "/job-postings/15/publish"]);
  expect(JSON.parse(mutations()[0][1]!.body as string)).toEqual({ job_description_id: 7, posting_id: 15,
    application_url: post.application_url, application_deadline: "2026-11-06", additional_instructions: "Attach your CV and portfolio." });
  expect(window.confirm).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("status").textContent).toBe("Job post published to Discord.");
  expect(screen.queryByRole("article", { name: "Discord post preview" })).toBeNull();
  expect(screen.queryByLabelText("Application link")).toBeNull();
  expect(screen.queryByRole("button", { name: "Publish to Discord" })).toBeNull();
  expect(screen.queryByText(/Preview #|JD v/)).toBeNull();
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Prepare job post" }));
});

it("retains the final confirmation before publishing the saved post", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  try {
    render(<DiscordJobPostPanel jobDescription={job} />);
    await screen.findByRole("article", { name: "Discord post preview" });
    await waitFor(() => expect((screen.getByRole("button", { name: "Publish to Discord" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "Publish to Discord" }));
    expect(mutations()).toHaveLength(0);
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Publish to Discord" }));
    await waitFor(() => expect(apiRequest).toHaveBeenCalledWith("/job-postings/15/publish", { method: "POST", body: JSON.stringify({ confirmed: true }) }));
    await screen.findByText("Job post published to Discord.");
  } finally { confirm.mockRestore(); }
});

it("creates a new preview and publishes the ID returned by saving", async () => {
  const original = vi.mocked(apiRequest).getMockImplementation()!;
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/job-postings/discord?job_description_id=7") return [];
    if (path === "/job-postings/discord/preview") return { ...post, id: 27 };
    if (path === "/job-postings/27/publish") return { ...post, id: 27, status: "published" };
    return original(path, options);
  });
  render(<DiscordJobPostPanel jobDescription={job} />);
  await waitFor(() => expect((screen.getByRole("button", { name: "Prepare job post" }) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "Prepare job post" }));
  expect(mutations()).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Publish to Discord" }));
  await screen.findByText("Job post published to Discord.");
  expect(JSON.parse(mutations()[0][1]!.body as string).posting_id).toBeNull();
  expect(mutations().map(([path]) => path)).toEqual(["/job-postings/discord/preview", "/job-postings/27/publish"]);
});

it("waits for saving and locks inputs and duplicate submissions until publication finishes", async () => {
  const original = vi.mocked(apiRequest).getMockImplementation()!;
  let release!: (value: DiscordJobPost) => void;
  const saving = new Promise<DiscordJobPost>(resolve => { release = resolve; });
  vi.mocked(apiRequest).mockImplementation(async (path, options) => path === "/job-postings/discord/preview" ? saving : original(path, options));
  render(<DiscordJobPostPanel jobDescription={job} />);
  await readyPanel();
  const publish = screen.getByRole("button", { name: "Publish to Discord" });
  fireEvent.click(publish);
  fireEvent.click(publish);
  fireEvent.submit(publish.closest("form")!);
  expect(mutations()).toHaveLength(1);
  expect(window.confirm).toHaveBeenCalledTimes(1);
  expect((screen.getByRole("button", { name: "Saving…" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByLabelText("Application link") as HTMLInputElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "Application deadline" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByLabelText("Additional application instructions") as HTMLTextAreaElement).disabled).toBe(true);
  release(post);
  await screen.findByText("Job post published to Discord.");
  expect(mutations()).toHaveLength(2);
});

it("never publishes after saving fails and keeps edited values for an explicit retry", async () => {
  const original = vi.mocked(apiRequest).getMockImplementation()!;
  let failed = false;
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/job-postings/discord/preview" && !failed) { failed = true; throw new Error("Synthetic save failure"); }
    return original(path, options);
  });
  render(<DiscordJobPostPanel jobDescription={job} />);
  await readyPanel();
  fireEvent.change(screen.getByLabelText("Additional application instructions"), { target: { value: "Keep these instructions" } });
  fireEvent.click(screen.getByRole("button", { name: "Publish to Discord" }));
  await screen.findByRole("alert");
  expect(screen.getByRole("article", { name: "Discord post preview" })).toBeTruthy();
  expect(screen.queryByText("Job post published to Discord.")).toBeNull();
  expect(mutations().map(([path]) => path)).toEqual(["/job-postings/discord/preview"]);
  expect((screen.getByLabelText("Additional application instructions") as HTMLTextAreaElement).value).toBe("Keep these instructions");
  fireEvent.click(screen.getByRole("button", { name: "Publish to Discord" }));
  await screen.findByText("Job post published to Discord.");
  expect(mutations().filter(([path]) => path.endsWith("/publish"))).toHaveLength(1);
});

it("does not publish content that changed after the user confirmed the displayed preview", async () => {
  const original = vi.mocked(apiRequest).getMockImplementation()!;
  vi.mocked(apiRequest).mockImplementation(async (path, options) => path === "/job-postings/discord/preview"
    ? { ...post, discord_payload: { embeds: [{ title: job.title, description: "A different job description" }] } } : original(path, options));
  render(<DiscordJobPostPanel jobDescription={job} />);
  await readyPanel();
  fireEvent.click(screen.getByRole("button", { name: "Publish to Discord" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Job details changed");
  expect(mutations()).toHaveLength(1);
});

it("does not automatically retry an uncertain publication", async () => {
  const original = vi.mocked(apiRequest).getMockImplementation()!;
  let attempted = false;
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/job-postings/15/publish") { attempted = true; throw new Error("Synthetic timeout"); }
    if (path === "/job-postings/discord?job_description_id=7" && attempted) return [{ ...post, status: "uncertain" }];
    return original(path, options);
  });
  render(<DiscordJobPostPanel jobDescription={job} />);
  await readyPanel();
  fireEvent.click(screen.getByRole("button", { name: "Publish to Discord" }));
  await screen.findByText(/Delivery is uncertain/);
  expect(screen.getByRole("article", { name: "Discord post preview" })).toBeTruthy();
  expect(screen.queryByText("Job post published to Discord.")).toBeNull();
  const publish = screen.getByRole("button", { name: "Publish to Discord" });
  expect((publish as HTMLButtonElement).disabled).toBe(true);
  fireEvent.submit(publish.closest("form")!);
  expect(mutations().filter(([path]) => path.endsWith("/publish"))).toHaveLength(1);
});

it("blocks another publication when delivery status cannot be refreshed", async () => {
  const original = vi.mocked(apiRequest).getMockImplementation()!;
  let attempted = false;
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/job-postings/15/publish") { attempted = true; throw new Error("Synthetic timeout"); }
    if (path === "/job-postings/discord?job_description_id=7" && attempted) throw new Error("Synthetic unavailable");
    return original(path, options);
  });
  render(<DiscordJobPostPanel jobDescription={job} />);
  await readyPanel();
  fireEvent.click(screen.getByRole("button", { name: "Publish to Discord" }));
  await screen.findByText(/Delivery could not be confirmed/);
  const publish = screen.getByRole("button", { name: "Publish to Discord" });
  expect((publish as HTMLButtonElement).disabled).toBe(true);
  fireEvent.submit(publish.closest("form")!);
  expect(mutations().filter(([path]) => path.endsWith("/publish"))).toHaveLength(1);
});

it("requires deliberately preparing a new publication after a previously published post", async () => {
  const original = vi.mocked(apiRequest).getMockImplementation()!;
  vi.mocked(apiRequest).mockImplementation(async (path, options) => path === "/job-postings/discord?job_description_id=7"
    ? [{ ...post, status: "published", external_url: "https://discord.com/channels/example/first" }, { ...post, id: 14, status: "published" }] : original(path, options));
  render(<DiscordJobPostPanel jobDescription={job} />);
  await waitFor(() => expect((screen.getByRole("button", { name: "Prepare job post" }) as HTMLButtonElement).disabled).toBe(false));
  expect(screen.queryByText("Publication history")).toBeNull();
  expect(screen.queryByText("published")).toBeNull();
  expect(screen.queryByRole("link", { name: "Open Discord message" })).toBeNull();
  expect(screen.queryByText("Job post published to Discord.")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Prepare job post" }));
  expect((screen.getByRole("button", { name: "Publish to Discord" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Prepare a new publication" }));
  expect((screen.getByRole("button", { name: "Publish to Discord" }) as HTMLButtonElement).disabled).toBe(false);
  expect(mutations()).toHaveLength(0);
});

it("shows success and closes the editor when status recovery confirms publication", async () => {
  const original = vi.mocked(apiRequest).getMockImplementation()!;
  let attempted = false;
  vi.mocked(apiRequest).mockImplementation(async (path, options) => {
    if (path === "/job-postings/15/publish") { attempted = true; throw new Error("Synthetic lost response"); }
    if (path === "/job-postings/discord?job_description_id=7" && attempted) return [{ ...post, status: "published" }];
    return original(path, options);
  });
  render(<DiscordJobPostPanel jobDescription={job} />);
  await readyPanel();
  fireEvent.click(screen.getByRole("button", { name: "Publish to Discord" }));
  expect((await screen.findByRole("status")).textContent).toBe("Job post published to Discord.");
  expect(screen.queryByRole("article", { name: "Discord post preview" })).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(mutations().filter(([path]) => path.endsWith("/publish"))).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Prepare job post" }));
  fireEvent.click(screen.getByRole("button", { name: "Prepare a new publication" }));
  expect(screen.queryByText("Job post published to Discord.")).toBeNull();
});

it("does not show success or collapse for an unconfirmed publish response", async () => {
  const original = vi.mocked(apiRequest).getMockImplementation()!;
  vi.mocked(apiRequest).mockImplementation(async (path, options) => path === "/job-postings/15/publish"
    ? { ...post, status: "uncertain" } : original(path, options));
  render(<DiscordJobPostPanel jobDescription={job} />);
  await readyPanel();
  fireEvent.click(screen.getByRole("button", { name: "Publish to Discord" }));
  await screen.findByRole("alert");
  expect(screen.queryByText("Job post published to Discord.")).toBeNull();
  expect(screen.getByRole("article", { name: "Discord post preview" })).toBeTruthy();
  expect((screen.getByRole("button", { name: "Publish to Discord" }) as HTMLButtonElement).disabled).toBe(true);
});

it("uses the styled calendar for deadlines and saves the selected ISO date", async () => {
  const { container } = render(<DiscordJobPostPanel jobDescription={job} />);
  await readyPanel();
  expect(container.querySelector('input[type="date"]')).toBeNull();
  const trigger = screen.getByRole("button", { name: "Application deadline" });
  expect(trigger.textContent).toContain("6 Nov 2026");
  fireEvent.click(trigger);
  const dialog = screen.getByRole("dialog", { name: "Choose application deadline" });
  expect(dialog.parentElement).toBe(document.body);
  expect(within(dialog).getByRole("button", { name: "November 6, 2026" }).getAttribute("aria-pressed")).toBe("true");
  fireEvent.click(within(dialog).getByRole("button", { name: "November 10, 2026" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(trigger);
  expect(trigger.textContent).toContain("10 Nov 2026");
  expect(within(screen.getByRole("article")).getByText("10 Nov 2026")).toBeTruthy();
  expect(mutations()).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Publish to Discord" }));
  await screen.findByText("Job post published to Discord.");
  expect(JSON.parse(mutations()[0][1]!.body as string).application_deadline).toBe("2026-11-10");
});

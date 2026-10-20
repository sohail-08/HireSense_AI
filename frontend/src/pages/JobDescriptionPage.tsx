import {
  FormEvent,
  useEffect,
  useState,
} from "react";

import {
  ApiError,
  apiRequest,
} from "../api/apiClient";
import { ErrorMessage } from "../components/common/ErrorMessage";
import { DiscordJobPostPanel } from "../components/jobs/DiscordJobPostPanel";
import { useSupervisor } from "../components/assistant/SupervisorProvider";
import type {
  JobDescriptionResponse,
  KnowledgeDocumentResponse,
  RequirementProfileDraft,
  SupervisorChatResponse,
} from "../types";

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Something went wrong. Please try again.";
}

function ItemList({
  items,
}: {
  items: { name: string; details: string | null }[];
}) {
  if (!items.length) {
    return <p className="text-sm text-slate-500">None specified.</p>;
  }

  return (
    <ul className="space-y-2 text-sm text-slate-700">
      {items.map((item) => (
        <li key={`${item.name}-${item.details ?? ""}`}>
          <span className="font-medium text-slate-900">{item.name}</span>
          {item.details ? ` — ${item.details}` : null}
        </li>
      ))}
    </ul>
  );
}

function DraftSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="border-t border-slate-200 pt-4">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h3>
      <div className="mt-2">{children}</div>
    </section>
  );
}

export function JobDescriptionPage() {
  const {
    response: supervisorResponse, loading: chatLoading,
    open: chatPanelOpen, setOpen: setChatPanelOpen, sendMessage,
    addTaskMessage, setSelectedJobDescriptionId, refreshVersion,
  } = useSupervisor();
  const [profile, setProfile] = useState<RequirementProfileDraft>();
  const [requirementProfileId, setRequirementProfileId] = useState<number>();
  const [jobDescription, setJobDescription] =
    useState<JobDescriptionResponse>();
  const [jobDescriptions, setJobDescriptions] =
    useState<JobDescriptionResponse[]>([]);
  const [jobListLoading, setJobListLoading] = useState(true);
  const [deletingJobId, setDeletingJobId] = useState<number>();
  const [draftTitle, setDraftTitle] = useState("");
  const [draftContent, setDraftContent] = useState("");
  const [saveLoading, setSaveLoading] = useState(false);
  const [postingRefreshKey, setPostingRefreshKey] = useState(0);
  const [error, setError] = useState<string>();
  const [knowledgeTitle, setKnowledgeTitle] = useState("");
  const [knowledgeFile, setKnowledgeFile] = useState<File>();
  const [knowledgeFileInputKey, setKnowledgeFileInputKey] = useState(0);
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);
  const [knowledgeNotice, setKnowledgeNotice] = useState<string>();
  const [knowledgeDocuments, setKnowledgeDocuments] =
    useState<KnowledgeDocumentResponse[]>([]);

  useEffect(() => {
    let active = true;
    apiRequest<KnowledgeDocumentResponse[]>("/knowledge/documents")
      .then((documents) => {
        if (active) setKnowledgeDocuments(documents);
      })
      .catch(() => {
        // The main workflow remains usable when the list cannot be loaded.
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (supervisorResponse) applySupervisorResponse(supervisorResponse);
    else {
      setProfile(undefined);
      setRequirementProfileId(undefined);
      setJobDescription(undefined);
      setDraftTitle("");
      setDraftContent("");
    }
  }, [supervisorResponse]);

  useEffect(() => {
    setSelectedJobDescriptionId(jobDescription?.id);
  }, [jobDescription?.id, setSelectedJobDescriptionId]);

  useEffect(() => {
    if (refreshVersion) void refreshWorkflowContents(supervisorResponse?.job_description?.id);
  }, [refreshVersion]);

  useEffect(() => {
    let active = true;
    apiRequest<JobDescriptionResponse[]>("/job-descriptions")
      .then((items) => {
        if (active) setJobDescriptions(items);
      })
      .catch((requestError) => {
        if (active) setError(getErrorMessage(requestError));
      })
      .finally(() => {
        if (active) setJobListLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  function upsertJobDescription(item: JobDescriptionResponse) {
    setJobDescriptions((current) => [
      item,
      ...current.filter((existing) => existing.id !== item.id),
    ]);
  }

  async function refreshWorkflowContents(selectedJobId?: number) {
    setPostingRefreshKey((current) => current + 1);
    try {
      const items = await apiRequest<JobDescriptionResponse[]>(
        "/job-descriptions",
      );
      setJobDescriptions(items);
      const targetId = selectedJobId ?? jobDescription?.id;
      if (targetId) {
        const refreshed = items.find((item) => item.id === targetId);
        if (refreshed) {
          setJobDescription(refreshed);
          setDraftTitle(refreshed.title);
          setDraftContent(refreshed.content);
        }
      }
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  }

  function applySupervisorResponse(response: SupervisorChatResponse) {
    const requirement = response.requirement_state;
    setProfile(requirement.profile);
    setRequirementProfileId(response.requirement_profile_id ?? undefined);

    if (response.job_description) {
      setJobDescription(response.job_description);
      setDraftTitle(response.job_description.title);
      setDraftContent(response.job_description.content);
      upsertJobDescription(response.job_description);
    } else {
      setJobDescription(undefined);
      setDraftTitle("");
      setDraftContent("");
    }
    if (response.job_posting || response.refresh_required) {
      setPostingRefreshKey((current) => current + 1);
    }
  }

  function selectJobDescription(item: JobDescriptionResponse) {
    setJobDescription(item);
    setDraftTitle(item.title);
    setDraftContent(item.content);
    setError(undefined);
  }

  async function addKnowledgeDocument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!knowledgeFile || knowledgeLoading) {
      return;
    }

    setKnowledgeLoading(true);
    setKnowledgeNotice(undefined);
    setError(undefined);
    try {
      const formData = new FormData();
      formData.append("file", knowledgeFile);
      if (knowledgeTitle.trim()) {
        formData.append("title", knowledgeTitle.trim());
      }
      const document = await apiRequest<KnowledgeDocumentResponse>(
        "/knowledge/documents/upload",
        {
          method: "POST",
          body: formData,
        },
      );
      setKnowledgeTitle("");
      setKnowledgeFile(undefined);
      setKnowledgeFileInputKey((current) => current + 1);
      setKnowledgeNotice(
        `Added “${document.title}”. Start a new chat to use the updated knowledge base.`,
      );
      setKnowledgeDocuments((current) => [
        document,
        ...current.filter((item) => item.id !== document.id),
      ]);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setKnowledgeLoading(false);
    }
  }

  async function deleteKnowledgeDocument(documentId: number) {
    const document = knowledgeDocuments.find((item) => item.id === documentId);
    if (
      !window.confirm(
        `Remove “${document?.title ?? "this document"}” from the knowledge base? ` +
          "The document and its indexed chunks will be deleted from the database.",
      )
    ) {
      return;
    }
    setError(undefined);
    try {
      await apiRequest<void>(`/knowledge/documents/${documentId}`, {
        method: "DELETE",
      });
      setKnowledgeDocuments((current) =>
        current.filter((document) => document.id !== documentId),
      );
      setKnowledgeNotice(
        `Removed “${document?.title ?? "knowledge document"}” from the database.`,
      );
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  }

  async function generateJobDescription() {
    if (!requirementProfileId || chatLoading) return;
    await sendMessage("Generate the job description.");
  }

  async function saveDraft() {
    if (!jobDescription || saveLoading) return;

    setError(undefined);
    setSaveLoading(true);
    try {
      const response = await apiRequest<JobDescriptionResponse>(
        `/job-descriptions/${jobDescription.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            title: draftTitle,
            content: draftContent,
          }),
        },
      );
      setJobDescription(response);
      setDraftTitle(response.title);
      setDraftContent(response.content);
      upsertJobDescription(response);
      addTaskMessage("success", "Job-description edits were saved.");
    } catch (requestError) {
      const message = getErrorMessage(requestError);
      setError(message);
      addTaskMessage("failure", `Could not save the job description. ${message}`);
    } finally {
      setSaveLoading(false);
    }
  }

  async function approveDraft() {
    if (!jobDescription || chatLoading) return;
    await sendMessage("Approve the current job description.");
  }

  async function createEditableRevision(item: JobDescriptionResponse) {
    if (saveLoading) return;

    setError(undefined);
    setSaveLoading(true);
    try {
      const response = await apiRequest<JobDescriptionResponse>(
        `/job-descriptions/${item.id}/revise`,
        { method: "POST" },
      );
      upsertJobDescription(response);
      selectJobDescription(response);
      addTaskMessage(
        "success",
        `Created editable version ${response.version} of “${response.title}”.`,
      );
    } catch (requestError) {
      const message = getErrorMessage(requestError);
      setError(message);
      addTaskMessage("failure", `Could not create an editable version. ${message}`);
    } finally {
      setSaveLoading(false);
    }
  }

  async function deleteJobDescription(item: JobDescriptionResponse) {
    if (
      deletingJobId ||
      !window.confirm(
        `Delete “${item.title}” version ${item.version} from HireSense? ` +
          "Any job post already published to Discord will remain there.",
      )
    ) {
      return;
    }

    setError(undefined);
    setDeletingJobId(item.id);
    try {
      await apiRequest<void>(`/job-descriptions/${item.id}`, {
        method: "DELETE",
      });
      setJobDescriptions((current) =>
        current.filter((existing) => existing.id !== item.id),
      );
      if (jobDescription?.id === item.id) {
        setJobDescription(undefined);
        setDraftTitle("");
        setDraftContent("");
      }
      addTaskMessage(
        "success",
        `Deleted “${item.title}” version ${item.version}.`,
      );
    } catch (requestError) {
      const message = getErrorMessage(requestError);
      setError(message);
      addTaskMessage("failure", `Could not delete the job description. ${message}`);
    } finally {
      setDeletingJobId(undefined);
    }
  }

  return (
    <section className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wide text-blue-600">
            F1 · Job Description Agent
          </p>
          <h1 className="mt-1 text-3xl font-bold tracking-tight text-slate-900">
            Create a job description
          </h1>
          <a className="mt-2 inline-block text-sm text-blue-700 underline" href="/interviewer/reports">View candidate assessment reports</a>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
            Describe the role conversationally. HireSense will clarify the
            requirements, use approved knowledge sources, and prepare a draft
            for your review.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {jobDescription ? (
            <span
              className={`inline-flex w-fit rounded-full px-3 py-1 text-sm font-semibold ${
                jobDescription.status === "approved"
                  ? "bg-emerald-100 text-emerald-700"
                  : "bg-amber-100 text-amber-700"
              }`}
            >
              {jobDescription.status === "approved" ? "Approved" : "Draft"} · v
              {jobDescription.version}
            </span>
          ) : null}
          {!chatPanelOpen ? (
            <button
              type="button"
              onClick={() => setChatPanelOpen(true)}
              aria-controls="supervisor-chat-panel"
              aria-expanded="false"
              className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                aria-hidden="true"
                className="size-4"
              >
                <path d="M8 10h8M8 14h5" strokeLinecap="round" />
                <path d="M6.5 19.5 3 21l1.1-3.8A8.5 8.5 0 1 1 6.5 19.5Z" strokeLinejoin="round" />
              </svg>
              Open assistant
            </button>
          ) : null}
        </div>
      </div>

      <ErrorMessage message={error} />

      <details className="mt-6 rounded-2xl border border-slate-200 bg-white shadow-sm">
        <summary className="cursor-pointer px-5 py-4 font-semibold text-slate-900">
          Add previous job description
          <span className="ml-2 text-sm font-normal text-slate-500">
            Used as RAG knowledge for future job descriptions
          </span>
        </summary>
        <form
          onSubmit={addKnowledgeDocument}
          className="grid gap-4 border-t border-slate-200 p-5 lg:grid-cols-2"
        >
          <div>
            <label htmlFor="knowledge-title" className="text-sm font-medium text-slate-700">
              Job description title (optional)
            </label>
            <input
              id="knowledge-title"
              value={knowledgeTitle}
              onChange={(event) => setKnowledgeTitle(event.target.value)}
              placeholder="Backend Engineer JD 2025"
              className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label htmlFor="knowledge-pdf" className="text-sm font-medium text-slate-700">
              Previous job description PDF
            </label>
            <input
              key={knowledgeFileInputKey}
              id="knowledge-pdf"
              type="file"
              accept="application/pdf,.pdf"
              onChange={(event) => setKnowledgeFile(event.target.files?.[0])}
              className="mt-1 block w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-blue-50 file:px-3 file:py-1.5 file:font-semibold file:text-blue-700"
            />
            <p className="mt-2 text-xs text-slate-500">
              Selectable-text PDFs only, up to 15 MB and 100 pages. The filename
              is used as the title when the optional title is empty.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3 lg:col-span-2">
            <button
              type="submit"
              disabled={
                knowledgeLoading ||
                !knowledgeFile
              }
              className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {knowledgeLoading ? "Extracting and embedding…" : "Upload and index PDF"}
            </button>
            {knowledgeNotice ? (
              <p className="text-sm text-emerald-700">{knowledgeNotice}</p>
            ) : null}
          </div>
          <div className="border-t border-slate-200 pt-4 lg:col-span-2">
            <h3 className="text-sm font-semibold text-slate-900">
              Current knowledge documents
            </h3>
            {knowledgeDocuments.length ? (
              <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                {knowledgeDocuments.map((document) => (
                  <li
                    key={document.id}
                    className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 px-3 py-2"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-slate-800">
                        {document.title}
                      </p>
                      <p className="text-xs text-slate-500">
                        {document.metadata_json.uploaded_pdf
                          ? `PDF · ${document.metadata_json.page_count ?? "?"} page(s)`
                          : document.metadata_json.synthetic
                            ? "Synthetic previous job description"
                            : "Previous job description"}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => void deleteKnowledgeDocument(document.id)}
                      className="shrink-0 text-xs font-semibold text-red-600 hover:text-red-700"
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-slate-500">
                No previous job descriptions have been added yet.
              </p>
            )}
          </div>
        </form>
      </details>

      <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 className="font-semibold text-slate-900">
              Created job descriptions
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Saved drafts and approved versions remain available after reload.
            </p>
          </div>
          <span className="text-sm font-medium text-slate-500">
            {jobDescriptions.length} saved
          </span>
        </div>

        {jobListLoading ? (
          <p className="mt-4 text-sm text-slate-500" role="status">
            Loading saved job descriptions…
          </p>
        ) : jobDescriptions.length ? (
          <ul className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {jobDescriptions.map((item) => {
              const selected = jobDescription?.id === item.id;
              return (
                <li
                  key={item.id}
                  className={`rounded-xl border p-4 ${
                    selected
                      ? "border-blue-400 bg-blue-50/50 ring-2 ring-blue-100"
                      : "border-slate-200"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate font-semibold text-slate-900">
                        {item.title}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        Version {item.version} · Updated{" "}
                        {new Date(item.updated_at).toLocaleString()}
                      </p>
                    </div>
                    <span
                      className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold ${
                        item.status === "approved"
                          ? "bg-emerald-100 text-emerald-700"
                          : "bg-amber-100 text-amber-700"
                      }`}
                    >
                      {item.status === "approved" ? "Approved" : "Draft"}
                    </span>
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => selectJobDescription(item)}
                      className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                    >
                      {selected ? "Selected" : item.status === "draft" ? "Edit" : "View"}
                    </button>
                    {item.status === "approved" ? (
                      <button
                        type="button"
                        onClick={() => void createEditableRevision(item)}
                        disabled={saveLoading}
                        className="rounded-lg border border-blue-300 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-100 disabled:opacity-50"
                      >
                        Edit as new draft
                      </button>
                    ) : null}
                    <button
                      type="button"
                      onClick={() => void deleteJobDescription(item)}
                      disabled={deletingJobId === item.id}
                      className="rounded-lg px-3 py-1.5 text-xs font-semibold text-red-600 hover:bg-red-50 disabled:opacity-50"
                    >
                      {deletingJobId === item.id ? "Deleting…" : "Delete"}
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="mt-4 rounded-xl bg-slate-50 px-4 py-5 text-sm text-slate-500">
            No job descriptions have been created yet.
          </p>
        )}
      </section>

      <div className="mt-8 grid items-start gap-6 xl:grid-cols-[minmax(0,0.72fr)_minmax(0,1.28fr)]">
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm xl:sticky xl:top-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="font-semibold text-slate-900">Requirement profile</h2>
                <p className="mt-1 text-sm text-slate-500">
                  This profile is sent to the JD agent after confirmation.
                </p>
              </div>
              {requirementProfileId ? (
                <span className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700">
                  Confirmed · #{requirementProfileId}
                </span>
              ) : null}
            </div>

            {profile ? (
              <div className="mt-5 space-y-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Role
                  </p>
                  <p className="mt-1 font-semibold text-slate-900">
                    {profile.title ?? "Not specified"}
                  </p>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Required skills
                    </p>
                    <div className="mt-2">
                      <ItemList items={profile.required_skills} />
                    </div>
                  </div>
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Preferred skills
                    </p>
                    <div className="mt-2">
                      <ItemList items={profile.preferred_skills} />
                    </div>
                  </div>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Qualifications
                  </p>
                  <div className="mt-2">
                    <ItemList items={profile.qualifications} />
                  </div>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Selection criteria
                  </p>
                  <div className="mt-2">
                    <ItemList items={profile.selection_criteria} />
                  </div>
                </div>
                <p className="text-sm text-slate-700">
                  <span className="font-semibold text-slate-900">Experience:</span>{" "}
                  {profile.min_years_experience === null
                    ? "Not specified"
                    : `${profile.min_years_experience}+ years`}
                </p>
                {supervisorResponse?.phase === "requirement_confirmation"
                  && supervisorResponse.requirement_state.proposal_ready
                  && !requirementProfileId ? (
                  <div className="flex justify-start border-t border-slate-200 pt-4">
                    <button
                      type="button"
                      onClick={() => void sendMessage("Use it.")}
                      disabled={chatLoading}
                      aria-label="Use this requirement profile"
                      className="rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-2 text-sm font-semibold text-emerald-700 transition hover:bg-emerald-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-600 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {chatLoading ? "Working…" : "Use it"}
                    </button>
                  </div>
                ) : null}
              </div>
            ) : (
              <p className="mt-5 rounded-xl bg-slate-50 px-4 py-5 text-sm text-slate-500">
                Your structured profile will appear here as you answer the chatbot.
              </p>
            )}
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="font-semibold text-slate-900">
                  {jobDescription ? "Job description" : "Job description draft"}
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  Generate only after confirming the requirement profile.
                </p>
              </div>
              <button
                type="button"
                onClick={() => void generateJobDescription()}
                disabled={!requirementProfileId || chatLoading || Boolean(jobDescription)}
                className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                {chatLoading ? "Working…" : "Generate JD"}
              </button>
            </div>

            {jobDescription ? (
              <div className="mt-5 space-y-5">
                <div>
                  <label
                    htmlFor="jd-title"
                    className="text-xs font-semibold uppercase tracking-wide text-slate-500"
                  >
                    Title
                  </label>
                  <input
                    id="jd-title"
                    value={draftTitle}
                    onChange={(event) => setDraftTitle(event.target.value)}
                    disabled={jobDescription.status !== "draft" || saveLoading}
                    className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-100"
                  />
                </div>

                <div>
                  <label
                    htmlFor="jd-content"
                    className="text-xs font-semibold uppercase tracking-wide text-slate-500"
                  >
                    Editable content
                  </label>
                  <textarea
                    id="jd-content"
                    value={draftContent}
                    onChange={(event) => setDraftContent(event.target.value)}
                    disabled={jobDescription.status !== "draft" || saveLoading}
                    rows={16}
                    className="mt-2 w-full resize-y rounded-xl border border-slate-300 px-3 py-3 font-mono text-sm leading-6 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-100"
                  />
                </div>

                {jobDescription.status === "draft" ? (
                  <div className="flex flex-wrap gap-3">
                    <button
                      type="button"
                      onClick={() => void saveDraft()}
                      disabled={saveLoading || !draftTitle.trim() || !draftContent.trim()}
                      className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {saveLoading ? "Saving…" : "Save edits"}
                    </button>
                    <button
                      type="button"
                      onClick={() => void approveDraft()}
                      disabled={saveLoading || chatLoading}
                      className="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-slate-300"
                    >
                      Approve JD
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => void createEditableRevision(jobDescription)}
                    disabled={saveLoading}
                    className="rounded-xl border border-blue-300 bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-700 transition hover:bg-blue-100 disabled:opacity-50"
                  >
                    {saveLoading ? "Creating draft…" : "Edit as new draft"}
                  </button>
                )}

                {jobDescription.status === "approved" ? (
                  <DiscordJobPostPanel
                    jobDescription={jobDescription}
                    refreshKey={postingRefreshKey}
                  />
                ) : null}

                <div className="rounded-xl bg-slate-50 p-4">
                  <h3 className="text-sm font-semibold text-slate-900">
                    Structured preview
                  </h3>
                  <div className="mt-3 space-y-4 text-sm text-slate-700">
                    <DraftSection title="Summary">
                      <p>{jobDescription.structured_content.summary}</p>
                    </DraftSection>
                    <DraftSection title="Responsibilities">
                      <ul className="list-disc space-y-1 pl-5">
                        {jobDescription.structured_content.responsibilities.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </DraftSection>
                    <DraftSection title="Required skills">
                      <ItemList items={jobDescription.structured_content.required_skills} />
                    </DraftSection>
                    <DraftSection title="Preferred skills">
                      <ItemList items={jobDescription.structured_content.preferred_skills} />
                    </DraftSection>
                    <DraftSection title="Qualifications">
                      <ItemList items={jobDescription.structured_content.qualifications} />
                    </DraftSection>
                    <DraftSection title="Experience">
                      <p>{jobDescription.structured_content.experience_requirement}</p>
                    </DraftSection>
                  </div>
                </div>

                <div className="border-t border-slate-200 pt-5">
                  <h3 className="text-sm font-semibold text-slate-900">
                    Supporting knowledge sources
                  </h3>
                  {jobDescription.source_references.length ? (
                    <ul className="mt-3 space-y-2">
                      {jobDescription.source_references.map((source) => (
                        <li
                          key={`${source.document_id}-${source.chunk_id}`}
                          className="rounded-xl border border-slate-200 px-3 py-2 text-sm"
                        >
                          <p className="font-medium text-slate-800">
                            {source.document_title}
                          </p>
                          <p className="mt-1 text-xs text-slate-500">
                            Chunk {source.chunk_index + 1} · relevance{" "}
                            {source.score.toFixed(2)}
                          </p>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-2 text-sm text-slate-500">
                      No knowledge-base sources were retrieved for this draft.
                    </p>
                  )}
                </div>
              </div>
            ) : (
              <p className="mt-5 rounded-xl bg-slate-50 px-4 py-5 text-sm text-slate-500">
                The generated draft will appear here after the requirement profile is confirmed.
              </p>
            )}
          </section>
      </div>

    </section>
  );
}

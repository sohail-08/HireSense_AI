import {
  FormEvent,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  ApiError,
  apiRequest,
} from "../api/apiClient";
import { ErrorMessage } from "../components/common/ErrorMessage";
import type {
  JobDescriptionDraft,
  JobDescriptionEvidence,
  JobDescriptionResponse,
  KnowledgeDocumentResponse,
  KnowledgeSourceType,
  RequirementChatResponse,
  RequirementChatStatus,
  RequirementProfileDraft,
} from "../types";

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

const initialAssistantMessage =
  "Tell me the role you want to hire for. I’ll search previous job descriptions and company policies, then propose requirements for you to accept or change.";

const fieldLabels: Record<string, string> = {
  title: "role/title",
  required_skills: "required skills",
  qualifications: "qualifications",
  experience: "experience requirement",
  selection_criteria: "selection criteria",
};

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
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "assistant", content: initialAssistantMessage },
  ]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string>();
  const [profile, setProfile] = useState<RequirementProfileDraft>();
  const [missingFields, setMissingFields] = useState<string[]>([]);
  const [chatStatus, setChatStatus] =
    useState<RequirementChatStatus>("active");
  const [knowledgeStatus, setKnowledgeStatus] =
    useState<RequirementChatResponse["knowledge_status"]>("not_searched");
  const [requirementSources, setRequirementSources] =
    useState<JobDescriptionEvidence[]>([]);
  const [proposalReady, setProposalReady] = useState(false);
  const [requirementProfileId, setRequirementProfileId] = useState<number>();
  const [jobDescription, setJobDescription] =
    useState<JobDescriptionResponse>();
  const [draftTitle, setDraftTitle] = useState("");
  const [draftContent, setDraftContent] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [generationLoading, setGenerationLoading] = useState(false);
  const [saveLoading, setSaveLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [knowledgeTitle, setKnowledgeTitle] = useState("");
  const [knowledgeContent, setKnowledgeContent] = useState("");
  const [knowledgeType, setKnowledgeType] =
    useState<KnowledgeSourceType>("previous_job_description");
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

  const canConfirm = Boolean(
    sessionId &&
      profile &&
      proposalReady &&
      chatStatus === "awaiting_confirmation" &&
      !requirementProfileId,
  );

  const formattedMissingFields = useMemo(
    () => missingFields.map((field) => fieldLabels[field] ?? field),
    [missingFields],
  );

  async function sendMessage(message: string) {
    const trimmedMessage = message.trim();
    if (!trimmedMessage || chatLoading) return;

    setError(undefined);
    setChatLoading(true);
    setMessages((current) => [
      ...current,
      { role: "user", content: trimmedMessage },
    ]);
    setInput("");

    try {
      const response = await apiRequest<RequirementChatResponse>(
        "/requirements/chat",
        {
          method: "POST",
          body: JSON.stringify({
            session_id: sessionId,
            message: trimmedMessage,
          }),
        },
      );

      setSessionId(response.session_id);
      setProfile(response.profile);
      setMissingFields(response.missing_fields);
      setChatStatus(response.status);
      setKnowledgeStatus(response.knowledge_status);
      setRequirementSources(response.source_references);
      setProposalReady(response.proposal_ready);
      if (response.requirement_profile_id) {
        setRequirementProfileId(response.requirement_profile_id);
      }
      setMessages((current) => [
        ...current,
        { role: "assistant", content: response.assistant_message },
      ]);

      if (response.error) {
        setError(response.error);
      }
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setChatLoading(false);
    }
  }

  function startNewSession() {
    setMessages([{ role: "assistant", content: initialAssistantMessage }]);
    setInput("");
    setSessionId(undefined);
    setProfile(undefined);
    setMissingFields([]);
    setChatStatus("active");
    setKnowledgeStatus("not_searched");
    setRequirementSources([]);
    setProposalReady(false);
    setRequirementProfileId(undefined);
    setJobDescription(undefined);
    setDraftTitle("");
    setDraftContent("");
    setError(undefined);
  }

  async function addKnowledgeDocument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!knowledgeTitle.trim() || !knowledgeContent.trim() || knowledgeLoading) {
      return;
    }

    setKnowledgeLoading(true);
    setKnowledgeNotice(undefined);
    setError(undefined);
    try {
      const document = await apiRequest<KnowledgeDocumentResponse>(
        "/knowledge/documents",
        {
          method: "POST",
          body: JSON.stringify({
            title: knowledgeTitle,
            content: knowledgeContent,
            source_type: knowledgeType,
            metadata: {},
          }),
        },
      );
      setKnowledgeTitle("");
      setKnowledgeContent("");
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
    setError(undefined);
    try {
      await apiRequest<void>(`/knowledge/documents/${documentId}`, {
        method: "DELETE",
      });
      setKnowledgeDocuments((current) =>
        current.filter((document) => document.id !== documentId),
      );
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  }

  function handleChatSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendMessage(input);
  }

  async function generateJobDescription() {
    if (!requirementProfileId || generationLoading) return;

    setError(undefined);
    setGenerationLoading(true);
    try {
      const response = await apiRequest<JobDescriptionResponse>(
        "/job-descriptions/generate",
        {
          method: "POST",
          body: JSON.stringify({
            requirement_profile_id: requirementProfileId,
          }),
        },
      );
      setJobDescription(response);
      setDraftTitle(response.title);
      setDraftContent(response.content);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setGenerationLoading(false);
    }
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
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setSaveLoading(false);
    }
  }

  async function approveDraft() {
    if (!jobDescription || saveLoading) return;

    setError(undefined);
    setSaveLoading(true);
    try {
      const response = await apiRequest<JobDescriptionResponse>(
        `/job-descriptions/${jobDescription.id}/approve`,
        { method: "POST" },
      );
      setJobDescription(response);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setSaveLoading(false);
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
          <button
            type="button"
            onClick={startNewSession}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            Start new session
          </button>
        </div>
      </div>

      <ErrorMessage message={error} />

      <details className="mt-6 rounded-2xl border border-slate-200 bg-white shadow-sm">
        <summary className="cursor-pointer px-5 py-4 font-semibold text-slate-900">
          Add company knowledge
          <span className="ml-2 text-sm font-normal text-slate-500">
            Previous JDs and hiring policies
          </span>
        </summary>
        <form
          onSubmit={addKnowledgeDocument}
          className="grid gap-4 border-t border-slate-200 p-5 lg:grid-cols-2"
        >
          <div className="space-y-4">
            <div>
              <label htmlFor="knowledge-type" className="text-sm font-medium text-slate-700">
                Document type
              </label>
              <select
                id="knowledge-type"
                value={knowledgeType}
                onChange={(event) =>
                  setKnowledgeType(event.target.value as KnowledgeSourceType)
                }
                className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="previous_job_description">Previous job description</option>
                <option value="company_policy">Company hiring policy</option>
              </select>
            </div>
            <div>
              <label htmlFor="knowledge-title" className="text-sm font-medium text-slate-700">
                Title
              </label>
              <input
                id="knowledge-title"
                value={knowledgeTitle}
                onChange={(event) => setKnowledgeTitle(event.target.value)}
                placeholder="Backend Engineer JD 2025"
                className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
          </div>
          <div>
            <label htmlFor="knowledge-content" className="text-sm font-medium text-slate-700">
              Document content
            </label>
            <textarea
              id="knowledge-content"
              value={knowledgeContent}
              onChange={(event) => setKnowledgeContent(event.target.value)}
              rows={7}
              placeholder="Paste the approved previous JD or company policy here."
              className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div className="flex flex-wrap items-center gap-3 lg:col-span-2">
            <button
              type="submit"
              disabled={
                knowledgeLoading ||
                !knowledgeTitle.trim() ||
                !knowledgeContent.trim()
              }
              className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {knowledgeLoading ? "Embedding document…" : "Add to knowledge base"}
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
                        {document.source_type.replaceAll("_", " ")}
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
                No company knowledge has been added yet.
              </p>
            )}
          </div>
        </form>
      </details>

      <div className="mt-8 grid gap-6 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <section className="flex min-h-[640px] flex-col rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-200 px-5 py-4">
            <div className="flex items-center justify-between gap-3">
              <h2 className="font-semibold text-slate-900">Requirement chat</h2>
              <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
                {knowledgeStatus === "found"
                  ? "Company data found"
                  : knowledgeStatus === "empty"
                    ? "No matching data"
                    : knowledgeStatus === "error"
                      ? "Retrieval error"
                      : "Ready to search"}
              </span>
            </div>
            <p className="mt-1 text-sm text-slate-500">
              Required details are collected before the profile can be confirmed.
            </p>
          </div>

          <div className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
            {messages.map((message, index) => (
              <div
                key={`${message.role}-${index}`}
                className={`flex ${
                  message.role === "user" ? "justify-end" : "justify-start"
                }`}
              >
                <div
                  className={`max-w-[90%] rounded-2xl px-4 py-3 text-sm leading-6 ${
                    message.role === "user"
                      ? "rounded-br-sm bg-blue-600 text-white"
                      : "rounded-bl-sm bg-slate-100 text-slate-700"
                  }`}
                >
                  {message.content}
                </div>
              </div>
            ))}

            {chatLoading ? (
              <p className="text-sm text-slate-500" role="status">
                Searching company knowledge and preparing a proposal…
              </p>
            ) : null}
          </div>

          {requirementSources.length ? (
            <div className="border-t border-slate-200 bg-blue-50/60 px-5 py-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">
                Sources used for this proposal
              </p>
              <ul className="mt-2 space-y-1 text-xs text-slate-600">
                {requirementSources.map((source) => (
                  <li key={`${source.document_id}-${source.chunk_id}`}>
                    {source.document_title} · {source.source_type.replaceAll("_", " ")} ·
                    relevance {source.score.toFixed(2)}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {formattedMissingFields.length ? (
            <p className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
              Still needed: {formattedMissingFields.join(", ")}.
            </p>
          ) : null}

          <form
            onSubmit={handleChatSubmit}
            className="border-t border-slate-200 p-4"
          >
            <label
              htmlFor="requirement-message"
              className="sr-only"
            >
              Requirement message
            </label>
            <div className="flex gap-2">
              <input
                id="requirement-message"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="e.g. Python and FastAPI are required…"
                disabled={chatLoading || Boolean(requirementProfileId)}
                className="min-w-0 flex-1 rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-100"
              />
              <button
                type="submit"
                disabled={chatLoading || !input.trim() || Boolean(requirementProfileId)}
                className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                Send
              </button>
            </div>

            {canConfirm ? (
              <button
                type="button"
                onClick={() => void sendMessage("use company defaults")}
                disabled={chatLoading}
                className="mt-3 w-full rounded-xl border border-emerald-300 bg-emerald-50 px-4 py-2 text-sm font-semibold text-emerald-700 transition hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Use company defaults
              </button>
            ) : null}
          </form>
        </section>

        <div className="space-y-6">
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
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
                <h2 className="font-semibold text-slate-900">Job description draft</h2>
                <p className="mt-1 text-sm text-slate-500">
                  Generate only after confirming the requirement profile.
                </p>
              </div>
              <button
                type="button"
                onClick={() => void generateJobDescription()}
                disabled={!requirementProfileId || generationLoading || Boolean(jobDescription)}
                className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                {generationLoading ? "Generating…" : "Generate JD"}
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
                      disabled={saveLoading}
                      className="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-slate-300"
                    >
                      Approve JD
                    </button>
                  </div>
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
                            {source.source_type.replaceAll("_", " ")} · chunk{" "}
                            {source.chunk_index + 1} · relevance {source.score.toFixed(2)}
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
      </div>
    </section>
  );
}

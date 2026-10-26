import { useEffect, useMemo, useRef, useState } from "react";

import { ApiError, apiRequest } from "../../api/apiClient";
import { DateTimePicker } from "../common/DateTimePicker";
import { DiscordPostPreview } from "./DiscordPostPreview";
import type {
  DiscordJobPost,
  DiscordPostDefaults,
  JobDescriptionResponse,
} from "../../types";


type PostForm = {
  applicationUrl: string;
  applicationDeadline: string;
  additionalInstructions: string;
};

const emptyForm: PostForm = {
  applicationUrl: "",
  applicationDeadline: "",
  additionalInstructions: "",
};

function errorMessage(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : "The request failed. Please try again.";
}

function formFromDefaults(defaults: DiscordPostDefaults): PostForm {
  return {
    applicationUrl: defaults.application_url ?? "",
    applicationDeadline: defaults.application_deadline ?? "",
    additionalInstructions: defaults.additional_instructions ?? "",
  };
}

function formFromPost(post: DiscordJobPost): PostForm {
  return {
    applicationUrl: post.application_url ?? "",
    applicationDeadline: post.application_deadline ?? "",
    additionalInstructions: post.additional_instructions ?? "",
  };
}

function matchesCompanyDetails(post: DiscordJobPost, defaults: DiscordPostDefaults, job: JobDescriptionResponse) {
  const embeds = post.discord_payload?.embeds;
  return post.heading === defaults.heading && post.contact_email === defaults.contact_email
    && post.location === defaults.location && Array.isArray(embeds)
    && embeds[0]?.title === job.title
    && embeds[0]?.description === (defaults.job_description_content ?? job.content);
}

export function DiscordJobPostPanel({
  jobDescription,
  refreshKey = 0,
}: {
  jobDescription: JobDescriptionResponse;
  refreshKey?: number;
}) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<PostForm>(emptyForm);
  const [companyDetails, setCompanyDetails] = useState<DiscordPostDefaults>();
  const [mcpConfigured, setMcpConfigured] = useState(false);
  const [savedPreview, setSavedPreview] = useState<DiscordJobPost>();
  const [loading, setLoading] = useState(true);
  const [savingPreview, setSavingPreview] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [deliveryUnknown, setDeliveryUnknown] = useState(false);
  const actionBusy = useRef(false);
  const editorButton = useRef<HTMLButtonElement>(null);
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(undefined);
    setCompanyDetails(undefined);
    setDeliveryUnknown(false);
    setMcpConfigured(false);
    Promise.all([
      apiRequest<DiscordPostDefaults>(`/job-postings/discord/defaults?job_description_id=${jobDescription.id}`),
      apiRequest<DiscordJobPost[]>(
        `/job-postings/discord?job_description_id=${jobDescription.id}`,
      ),
    ])
      .then(([defaults, posts]) => {
        if (!active) return;
        setMcpConfigured(defaults.mcp_configured);
        setCompanyDetails(defaults);
        const editablePreview = posts.find((post) => post.status === "draft");
        if (editablePreview) {
          setSavedPreview(editablePreview);
          setForm(formFromPost(editablePreview));
          if (
            editablePreview.application_url &&
            editablePreview.application_deadline
          ) {
            setOpen(true);
          }
        } else {
          setSavedPreview(posts[0]);
          setForm(formFromDefaults(defaults));
        }
      })
      .catch((requestError) => {
        if (active) setError(errorMessage(requestError));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [jobDescription.id, refreshKey]);

  const footerRows = useMemo(
    () => [
      ["Application link", form.applicationUrl],
      ["Contact email", companyDetails?.contact_email ?? ""],
      ["Address", companyDetails?.location ?? ""],
      ["Application deadline", form.applicationDeadline],
      ["Additional application instructions", form.additionalInstructions],
    ].filter(([, value]) => value.trim()),
    [form, companyDetails],
  );

  function updateField(field: keyof PostForm, value: string) {
    if (actionBusy.current) return;
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function publish() {
    if (actionBusy.current || loading || !companyDetails || !mcpConfigured || deliveryUnknown
      || (savedPreview && savedPreview.status !== "draft")) return;
    if (!window.confirm("Save the current details and publish this job post to Discord now?")) return;

    actionBusy.current = true;
    setPublishing(true);
    setSavingPreview(true);
    setError(undefined);
    setNotice(undefined);
    let attemptedPostingId: number | undefined;
    try {
      const preview = await apiRequest<DiscordJobPost>("/job-postings/discord/preview", {
        method: "POST",
        body: JSON.stringify({
          job_description_id: jobDescription.id,
          posting_id: savedPreview?.id ?? null,
          application_url: form.applicationUrl || null,
          application_deadline: form.applicationDeadline || null,
          additional_instructions: form.additionalInstructions || null,
        }),
      });
      setSavedPreview(preview);
      setForm(formFromPost(preview));
      setSavingPreview(false);
      // The user confirmed the visible post, not a different JD or company
      // configuration that changed while the save request was in flight.
      if (preview.status !== "draft" || !matchesCompanyDetails(preview, companyDetails, jobDescription)) {
        setError("Job details changed. Reload and review the preview before publishing.");
        return;
      }

      attemptedPostingId = preview.id;
      const published = await apiRequest<DiscordJobPost>(`/job-postings/${preview.id}/publish`, {
        method: "POST", body: JSON.stringify({ confirmed: true }),
      });
      setSavedPreview(published);
      if (published.status === "published") {
        setNotice("Job post published to Discord.");
        setOpen(false);
      } else {
        setError("Publication has not been confirmed. Check the publication status before trying again.");
      }
    } catch (requestError) {
      setError(errorMessage(requestError));
      // Saving errors never reach publication. Once publication was attempted,
      // read its status but never automatically retry an external side effect.
      if (attemptedPostingId !== undefined) {
        setDeliveryUnknown(true);
        try {
          const posts = await apiRequest<DiscordJobPost[]>(
            `/job-postings/discord?job_description_id=${jobDescription.id}`,
          );
          const attempted = posts.find(item => item.id === attemptedPostingId);
          if (attempted) {
            setSavedPreview(attempted);
            if (attempted.status !== "draft") setDeliveryUnknown(false);
            if (attempted.status === "published") {
              setError(undefined);
              setNotice("Job post published to Discord.");
              setOpen(false);
            }
          }
        } catch {
          // Stay blocked until status can be verified by an explicit reload.
        }
      }
    } finally {
      setSavingPreview(false);
      setPublishing(false);
      actionBusy.current = false;
    }
  }

  function prepareNewPost() {
    if (actionBusy.current || deliveryUnknown) return;
    setSavedPreview(undefined);
    setOpen(true);
    setError(undefined);
    setNotice(undefined);
  }

  useEffect(() => {
    if (notice && !open && !publishing) editorButton.current?.focus();
  }, [notice, open, publishing]);

  return (
    <section id="job-publication" className="workflow-section rounded-2xl border border-indigo-200 bg-indigo-50/30 p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="font-semibold text-slate-900">Discord job posting</h3>
          <p className="mt-1 text-sm text-slate-600">
            Check your job post before publishing it to Discord.
          </p>
        </div>
        <button
          ref={editorButton}
          type="button"
          onClick={() => setOpen((current) => !current)}
          disabled={loading || publishing || !companyDetails}
          className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
        >
          {open ? "Close post editor" : "Prepare job post"}
        </button>
      </div>

      {loading ? (
        <p className="mt-4 text-sm text-slate-500" role="status">
          Loading publication status…
        </p>
      ) : null}

      {error ? (
        <p className="mt-4 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
          {error}
        </p>
      ) : null}

      {notice ? <div role="status" className="mt-4 flex items-center gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800">
        <svg aria-hidden="true" className="h-5 w-5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m6 12 4 4 8-8" strokeLinecap="round" strokeLinejoin="round" /></svg>{notice}
      </div> : null}

      {savedPreview?.status === "uncertain" ? (
        <p className="mt-4 rounded-xl bg-orange-50 px-3 py-2 text-sm text-orange-800">
          Delivery is uncertain. Check the Discord channel before deliberately preparing a new post.
        </p>
      ) : null}

      {deliveryUnknown ? <p role="alert" className="mt-4 rounded-xl bg-orange-50 px-3 py-2 text-sm text-orange-800">Delivery could not be confirmed. Reload and check the publication status before trying again.</p> : null}

      {open ? (
        <form onSubmit={event => { event.preventDefault(); void publish(); }} className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <div className="min-w-0 space-y-4">
            <div>
              <label htmlFor="discord-application-url" className="text-sm font-medium text-slate-700">
                Application link
              </label>
              <input
                id="discord-application-url"
                type="url"
                disabled={publishing || loading}
                value={form.applicationUrl}
                onChange={(event) => updateField("applicationUrl", event.target.value)}
                placeholder="https://forms.example.com/application"
                className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
              />
            </div>
            <DateTimePicker label="Application deadline" popupTitle="Choose application deadline" kind="date"
              disabled={publishing || loading} value={form.applicationDeadline}
              onChange={value => updateField("applicationDeadline", value)} />
            <div>
              <label htmlFor="discord-instructions" className="text-sm font-medium text-slate-700">
                Additional application instructions
              </label>
              <textarea
                id="discord-instructions"
                disabled={publishing || loading}
                value={form.additionalInstructions}
                onChange={(event) => updateField("additionalInstructions", event.target.value)}
                maxLength={1024}
                rows={4}
                className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
              />
            </div>
          </div>

          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-900">Discord preview</p>
            {companyDetails ? <DiscordPostPreview heading={companyDetails.heading} title={jobDescription.title} content={companyDetails.job_description_content ?? jobDescription.content} fields={footerRows} />
              : <p className="mt-2 rounded-xl bg-slate-50 p-4 text-sm text-slate-500">{loading ? "Loading post details…" : "Post details are unavailable. Please reload."}</p>}

            {!mcpConfigured ? (
              <p className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800">
                Configure the Discord bot token and channel ID on the job-posting MCP server before publishing.
              </p>
            ) : null}
            <div className="mt-4 flex flex-wrap gap-3">
              <button
                type="submit"
                disabled={
                  publishing ||
                  loading ||
                  !mcpConfigured ||
                  !companyDetails ||
                  deliveryUnknown ||
                  Boolean(savedPreview && savedPreview.status !== "draft")
                }
                className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                {savingPreview ? "Saving…" : publishing ? "Publishing…" : "Publish to Discord"}
              </button>
              {savedPreview && savedPreview.status !== "draft" ? (
                <button
                  type="button"
                  onClick={prepareNewPost}
                  disabled={publishing || deliveryUnknown}
                  className="rounded-xl px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-white"
                >
                  Prepare a new publication
                </button>
              ) : null}
            </div>
          </div>
        </form>
      ) : null}
    </section>
  );
}

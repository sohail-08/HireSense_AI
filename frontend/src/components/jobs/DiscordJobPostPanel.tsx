import { useEffect, useMemo, useState } from "react";

import { ApiError, apiRequest } from "../../api/apiClient";
import type {
  DiscordJobPost,
  DiscordPostDefaults,
  JobDescriptionResponse,
} from "../../types";


type PostForm = {
  heading: string;
  applicationUrl: string;
  contactEmail: string;
  location: string;
  applicationDeadline: string;
  additionalInstructions: string;
};

const emptyForm: PostForm = {
  heading: "BJIT is Hiring!",
  applicationUrl: "",
  contactEmail: "",
  location: "",
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
    heading: defaults.heading,
    applicationUrl: defaults.application_url ?? "",
    contactEmail: defaults.contact_email ?? "",
    location: defaults.location ?? "",
    applicationDeadline: defaults.application_deadline ?? "",
    additionalInstructions: defaults.additional_instructions ?? "",
  };
}

function formFromPost(post: DiscordJobPost): PostForm {
  return {
    heading: post.heading ?? "",
    applicationUrl: post.application_url ?? "",
    contactEmail: post.contact_email ?? "",
    location: post.location ?? "",
    applicationDeadline: post.application_deadline ?? "",
    additionalInstructions: post.additional_instructions ?? "",
  };
}

function statusStyle(status: DiscordJobPost["status"]): string {
  if (status === "published") return "bg-emerald-100 text-emerald-700";
  if (status === "failed") return "bg-red-100 text-red-700";
  if (status === "uncertain") return "bg-orange-100 text-orange-700";
  if (status === "publishing") return "bg-blue-100 text-blue-700";
  return "bg-amber-100 text-amber-700";
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
  const [webhookConfigured, setWebhookConfigured] = useState(false);
  const [publications, setPublications] = useState<DiscordJobPost[]>([]);
  const [savedPreview, setSavedPreview] = useState<DiscordJobPost>();
  const [previewCurrent, setPreviewCurrent] = useState(false);
  const [loading, setLoading] = useState(true);
  const [savingPreview, setSavingPreview] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string>();

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(undefined);
    Promise.all([
      apiRequest<DiscordPostDefaults>("/job-postings/discord/defaults"),
      apiRequest<DiscordJobPost[]>(
        `/job-postings/discord?job_description_id=${jobDescription.id}`,
      ),
    ])
      .then(([defaults, posts]) => {
        if (!active) return;
        setWebhookConfigured(defaults.webhook_configured);
        setPublications(posts);
        const editablePreview = posts.find((post) => post.status === "draft");
        if (editablePreview) {
          setSavedPreview(editablePreview);
          setForm(formFromPost(editablePreview));
          setPreviewCurrent(true);
          if (
            editablePreview.application_url &&
            editablePreview.application_deadline
          ) {
            setOpen(true);
          }
        } else {
          setSavedPreview(posts[0]);
          setForm(formFromDefaults(defaults));
          setPreviewCurrent(false);
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
      ["Contact email", form.contactEmail],
      ["Location", form.location],
      ["Application deadline", form.applicationDeadline],
      ["Additional application instructions", form.additionalInstructions],
    ].filter(([, value]) => value.trim()),
    [form],
  );

  function updateField(field: keyof PostForm, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    setPreviewCurrent(false);
  }

  async function savePreview() {
    if (!form.heading.trim() || savingPreview) return;
    setSavingPreview(true);
    setError(undefined);
    try {
      const preview = await apiRequest<DiscordJobPost>(
        "/job-postings/discord/preview",
        {
          method: "POST",
          body: JSON.stringify({
            job_description_id: jobDescription.id,
            posting_id:
              savedPreview?.status === "draft" ? savedPreview.id : null,
            heading: form.heading,
            application_url: form.applicationUrl || null,
            contact_email: form.contactEmail || null,
            location: form.location || null,
            application_deadline: form.applicationDeadline || null,
            additional_instructions: form.additionalInstructions || null,
          }),
        },
      );
      setSavedPreview(preview);
      setForm(formFromPost(preview));
      setPreviewCurrent(true);
      setPublications((current) => [
        preview,
        ...current.filter((item) => item.id !== preview.id),
      ]);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setSavingPreview(false);
    }
  }

  async function reloadPublications() {
    const posts = await apiRequest<DiscordJobPost[]>(
      `/job-postings/discord?job_description_id=${jobDescription.id}`,
    );
    setPublications(posts);
    if (posts[0]) setSavedPreview(posts[0]);
  }

  async function publish() {
    if (!savedPreview || savedPreview.status !== "draft" || !previewCurrent) {
      return;
    }
    if (!window.confirm("Publish the reviewed job post to Discord now?")) {
      return;
    }

    setPublishing(true);
    setError(undefined);
    try {
      const published = await apiRequest<DiscordJobPost>(
        `/job-postings/${savedPreview.id}/publish`,
        {
          method: "POST",
          body: JSON.stringify({ confirmed: true }),
        },
      );
      setSavedPreview(published);
      setPublications((current) => [
        published,
        ...current.filter((item) => item.id !== published.id),
      ]);
    } catch (requestError) {
      setError(errorMessage(requestError));
      try {
        await reloadPublications();
      } catch {
        // Preserve the publication error when status refresh is unavailable.
      }
    } finally {
      setPublishing(false);
    }
  }

  function prepareNewPost() {
    setSavedPreview(undefined);
    setPreviewCurrent(false);
    setOpen(true);
  }

  return (
    <section className="rounded-2xl border border-indigo-200 bg-indigo-50/30 p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="font-semibold text-slate-900">Discord job posting</h3>
          <p className="mt-1 text-sm text-slate-600">
            Review the exact message before publishing it to the configured channel.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setOpen((current) => !current)}
          className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
        >
          {open ? "Close post editor" : "Prepare job post"}
        </button>
      </div>

      {loading ? (
        <p className="mt-4 text-sm text-slate-500" role="status">
          Loading publication status…
        </p>
      ) : publications.length ? (
        <div className="mt-4 space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Publication history
          </p>
          {publications.slice(0, 5).map((post) => (
            <div
              key={post.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-sm text-slate-600">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${statusStyle(post.status)}`}>
                    {post.status}
                  </span>
                  <span>Preview #{post.id} · JD v{post.job_description_version}</span>
                </div>
                {post.error_message ? (
                  <p className="mt-1 text-xs text-slate-500">{post.error_message}</p>
                ) : null}
              </div>
              {post.external_url ? (
                <a
                  href={post.external_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm font-semibold text-indigo-700 hover:underline"
                >
                  Open Discord message
                </a>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}

      {error ? (
        <p className="mt-4 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
          {error}
        </p>
      ) : null}

      {savedPreview?.status === "uncertain" ? (
        <p className="mt-4 rounded-xl bg-orange-50 px-3 py-2 text-sm text-orange-800">
          Delivery is uncertain. Check the Discord channel before deliberately preparing a new post.
        </p>
      ) : null}

      {open ? (
        <div className="mt-5 grid gap-5 xl:grid-cols-2">
          <div className="space-y-4">
            <div>
              <label htmlFor="discord-heading" className="text-sm font-medium text-slate-700">
                Heading
              </label>
              <input
                id="discord-heading"
                value={form.heading}
                onChange={(event) => updateField("heading", event.target.value)}
                maxLength={2000}
                className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label htmlFor="discord-application-url" className="text-sm font-medium text-slate-700">
                Application link
              </label>
              <input
                id="discord-application-url"
                type="url"
                value={form.applicationUrl}
                onChange={(event) => updateField("applicationUrl", event.target.value)}
                placeholder="https://forms.example.com/application"
                className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="discord-contact-email" className="text-sm font-medium text-slate-700">
                  Contact email
                </label>
                <input
                  id="discord-contact-email"
                  type="email"
                  value={form.contactEmail}
                  onChange={(event) => updateField("contactEmail", event.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label htmlFor="discord-location" className="text-sm font-medium text-slate-700">
                  Location
                </label>
                <input
                  id="discord-location"
                  value={form.location}
                  onChange={(event) => updateField("location", event.target.value)}
                  className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
                />
              </div>
            </div>
            <div>
              <label htmlFor="discord-deadline" className="text-sm font-medium text-slate-700">
                Application deadline
              </label>
              <input
                id="discord-deadline"
                type="date"
                value={form.applicationDeadline}
                onChange={(event) => updateField("applicationDeadline", event.target.value)}
                className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label htmlFor="discord-instructions" className="text-sm font-medium text-slate-700">
                Additional application instructions
              </label>
              <textarea
                id="discord-instructions"
                value={form.additionalInstructions}
                onChange={(event) => updateField("additionalInstructions", event.target.value)}
                maxLength={1024}
                rows={4}
                className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
              />
            </div>
          </div>

          <div>
            <p className="text-sm font-semibold text-slate-900">Discord preview</p>
            <div className="mt-2 rounded-xl bg-slate-900 p-4 text-slate-100">
              <p className="whitespace-pre-wrap font-semibold">{form.heading || "Heading required"}</p>
              <div className="mt-3 border-l-4 border-indigo-400 bg-slate-800 p-4">
                <h4 className="font-semibold">{jobDescription.title}</h4>
                <div className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-200">
                  {jobDescription.content}
                </div>
                {footerRows.length ? (
                  <dl className="mt-4 space-y-3 border-t border-slate-600 pt-4 text-sm">
                    {footerRows.map(([label, value]) => (
                      <div key={label}>
                        <dt className="font-semibold text-slate-100">{label}</dt>
                        <dd className="mt-0.5 whitespace-pre-wrap text-slate-300">{value}</dd>
                      </div>
                    ))}
                  </dl>
                ) : null}
              </div>
            </div>

            {!webhookConfigured ? (
              <p className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800">
                Add DISCORD_WEBHOOK_URL to the backend environment before publishing.
              </p>
            ) : null}
            {!previewCurrent ? (
              <p className="mt-3 text-sm text-amber-700">
                Save this preview after every edit before publishing.
              </p>
            ) : null}

            <div className="mt-4 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => void savePreview()}
                disabled={savingPreview || !form.heading.trim()}
                className="rounded-xl border border-indigo-300 bg-white px-4 py-2 text-sm font-semibold text-indigo-700 hover:bg-indigo-50 disabled:opacity-50"
              >
                {savingPreview ? "Saving preview…" : "Save reviewed preview"}
              </button>
              <button
                type="button"
                onClick={() => void publish()}
                disabled={
                  publishing ||
                  !webhookConfigured ||
                  !previewCurrent ||
                  savedPreview?.status !== "draft"
                }
                className="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                {publishing ? "Publishing…" : "Publish to Discord"}
              </button>
              {savedPreview && savedPreview.status !== "draft" ? (
                <button
                  type="button"
                  onClick={prepareNewPost}
                  className="rounded-xl px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-white"
                >
                  Prepare a new publication
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}

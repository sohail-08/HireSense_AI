import type { SupervisorChatResponse } from "../../types";

export type WorkflowDestination = { path: string; section: string };

// Map structured tool outcomes, never prose/model-supplied arbitrary URLs.
export function workflowDestination(value: SupervisorChatResponse, selectedJob?: number): WorkflowDestination | undefined {
  if (value.outcome === "failure") return;
  const jobQuery = selectedJob ? `?job=${selectedJob}` : "";
  switch (value.route) {
    case "generate_job_description": case "edit_job_description": case "job_description":
      if (value.job_description) return { path: "/interviewer/jobs", section: "job-description-review" };
      return;
    case "approve_job_description": case "job_posting":
      if (value.job_description) return { path: "/interviewer/jobs", section: value.job_description.status === "approved" ? "job-publication" : "job-description-review" };
      return;
    case "sync_responses":
      if (value.sync_result) return { path: "/interviewer/candidates", section: "candidate-list" };
      return;
    case "screen_candidates":
      return { path: `/interviewer/assessments${value.screening_batch ? `?job=${value.screening_batch.job_posting_id}` : jobQuery}`, section: "cv-screening" };
    case "interviews":
      return ["interview_sent", "interview_reschedule"].includes(value.phase)
        ? { path: "/interviewer/interviews", section: "interview-list" }
        : { path: `/interviewer/schedule-interviews${value.interview_selection ? `?job=${value.interview_selection.job_posting_id}` : jobQuery}`, section: "interview-candidates" };
    case "candidate_assessments": {
      const links = value.assessment_links ?? [];
      if (!links.length) return;
      if (links.length > 1) return { path: `/interviewer/reports${jobQuery}`, section: "final-ranking" };
      let url: URL;
      try { url = new URL(links[0].path, window.location.origin); } catch { return; }
      if (url.origin !== window.location.origin || url.pathname !== "/interviewer/reports") return;
      const params = new URLSearchParams();
      for (const key of ["job", "application", "run", "comparison"]) {
        const id = url.searchParams.get(key);
        if (id && /^[1-9]\d*$/.test(id)) params.set(key, id);
      }
      return { path: `/interviewer/reports${params.size ? `?${params}` : ""}`, section: params.has("run") || params.has("comparison") ? "assessment-details" : "final-ranking" };
    }
  }
}

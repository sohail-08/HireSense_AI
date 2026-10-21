import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";

const workspaces = [
  {
    path: "jobs",
    title: "Jobs",
    description: "Create and manage job descriptions and job posts.",
    accent: "border-t-sky-300",
  },
  {
    path: "candidates",
    title: "Candidates",
    description: "Review candidate profiles and CV information.",
    accent: "border-t-teal-300",
  },
  {
    path: "interviews",
    title: "Interviews",
    description: "Manage interviews and access interview support.",
    accent: "border-t-violet-300",
  },
  {
    path: "assessments",
    title: "Assessments",
    description: "Review assessments and candidate evaluations.",
    accent: "border-t-amber-300",
  },
];

export function InterviewerDashboard() {
  const { user } = useAuth();

  return (
    <section className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
      <h1 className="text-3xl font-bold tracking-tight text-slate-900">
        Interviewer dashboard
      </h1>

      <p className="mt-2 text-slate-600">
        Welcome, {user?.name}. Your recruitment workspace is ready.
      </p>

      <div className="mt-8 grid grid-cols-1 gap-5 sm:grid-cols-2">
        {workspaces.map((workspace) => (
          <Link
            key={workspace.path}
            to={`/interviewer/${workspace.path}`}
            className={`group rounded-2xl border border-slate-200 border-t-4 bg-white p-6 shadow-sm transition hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 ${workspace.accent}`}
          >
            <h2 className="text-xl font-semibold text-slate-900 transition group-hover:text-blue-700">
              {workspace.title}
            </h2>

            <p className="mt-2 text-sm leading-6 text-slate-600">
              {workspace.description}
            </p>

            <span className="mt-5 inline-flex items-center gap-2 text-sm font-semibold text-blue-600">
              Open workspace
              <span aria-hidden="true">→</span>
            </span>
          </Link>
        ))}
      </div>

      <p className="mt-6 text-sm leading-6 text-slate-500">
        Authentication and navigation are implemented.
        Recruitment features will follow.
      </p>
    </section>
  );
}

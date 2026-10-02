import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";

export function CandidateDashboard() {
  const { user } = useAuth();

  return (
    <section className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
      <h1 className="text-3xl font-bold tracking-tight text-slate-900">
        Candidate dashboard
      </h1>

      <p className="mt-2 text-slate-600">
        Welcome, {user?.name}.
      </p>

      <div className="mt-8 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-xl font-semibold text-slate-900">
          Your account
        </h2>

        <dl className="mt-5 space-y-4">
          <div>
            <dt className="text-sm font-medium text-slate-500">
              Email
            </dt>
            <dd className="mt-1 break-all text-slate-900">
              {user?.email}
            </dd>
          </div>

          <div>
            <dt className="text-sm font-medium text-slate-500">
              Role
            </dt>
            <dd className="mt-1">
              <span className="inline-flex rounded-full bg-blue-50 px-3 py-1 text-sm font-medium text-blue-700">
                Candidate
              </span>
            </dd>
          </div>
        </dl>

        <Link
          to="/candidate/interviews"
          className="mt-6 inline-flex items-center justify-center rounded-lg bg-blue-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
        >
          View interviews
        </Link>
      </div>
    </section>
  );
}
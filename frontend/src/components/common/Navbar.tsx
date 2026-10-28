import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../../auth/AuthProvider";
import { ApplicationNotifications } from "./ApplicationNotifications";

export function Navbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  if (!user || user.role !== "interviewer") return null;

  const prefix = "/interviewer";

  const links = [
    { page: "jobs", label: "Jobs" },
    { page: "candidates", label: "Candidates" },
    { page: "assessments", label: "CV Screening" },
    { page: "schedule-interviews", label: "Schedule Interviews" },
    { page: "interviews", label: "Interview" },
    { page: "reports", label: "Assessment" },
  ];

  function handleLogout() {
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <header className="interviewer-navbar sticky top-0 z-30 border-b border-blue-100 bg-white shadow-sm shadow-blue-900/5">
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-4 px-4 py-4 sm:px-6">
        <NavLink
          to={`${prefix}/dashboard`}
          className="shrink-0 text-xl font-bold tracking-tight text-blue-600 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-blue-600"
        >
          HireSense
        </NavLink>

        <nav
          aria-label="Main navigation"
          className="order-last flex w-full flex-wrap gap-2 lg:order-none lg:w-auto lg:flex-1"
        >
          {links.map(({ page, label }) => (
            <NavLink
              key={page}
              to={`${prefix}/${page}`}
              className={({ isActive }) =>
                [
                  "rounded-xl border px-3 py-2 text-sm font-medium transition",
                  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600",
                  isActive
                    ? "border-blue-200 bg-blue-50 text-blue-800 shadow-sm shadow-blue-900/5"
                    : "border-transparent text-slate-600 hover:border-blue-100 hover:bg-blue-50/60 hover:text-blue-800",
                ].join(" ")
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex min-w-0 items-center gap-3">
          {user.role === "interviewer" ? <ApplicationNotifications /> : null}
          <div className="hidden min-w-0 text-right sm:block">
            <p className="max-w-40 truncate text-sm font-semibold text-slate-900">
              {user.name}
            </p>

            <p className="text-xs capitalize text-slate-500">
              {user.role}
            </p>
          </div>

          <button
            type="button"
            onClick={handleLogout}
            className="shrink-0 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
          >
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}

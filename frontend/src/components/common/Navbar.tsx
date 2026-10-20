import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../../auth/AuthProvider";
import { ApplicationNotifications } from "./ApplicationNotifications";

export function Navbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  if (!user) return null;

  const prefix = `/${user.role}`;

  const links =
    user.role === "interviewer"
      ? [
          "dashboard",
          "jobs",
          "candidates",
          "interviews",
          "assessments",
          "reports",
        ]
      : ["dashboard", "interviews"];

  function handleLogout() {
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <header className="interviewer-navbar sticky top-0 z-30 border-b border-slate-200 bg-white">
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
          {links.map((page) => (
            <NavLink
              key={page}
              to={`${prefix}/${page}`}
              className={({ isActive }) =>
                [
                  "rounded-lg px-3 py-2 text-sm font-medium transition",
                  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600",
                  isActive
                    ? "bg-blue-50 text-blue-700"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
                ].join(" ")
              }
            >
              {page.charAt(0).toUpperCase() + page.slice(1)}
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

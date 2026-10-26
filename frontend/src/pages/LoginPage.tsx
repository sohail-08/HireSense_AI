import { useState, type FormEvent } from "react";
import {
  Navigate,
  useNavigate,
} from "react-router-dom";

import { dashboardPath, useAuth } from "../auth/AuthProvider";
import { ErrorMessage } from "../components/common/ErrorMessage";
import { LoadingSpinner } from "../components/common/LoadingSpinner";

const inputClassName =
  "mt-2 block w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-200";

export function LoginPage() {
  const { user, loading, login } = useAuth();

  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (loading) {
    return <LoadingSpinner />;
  }

  if (user?.role === "interviewer") {
    return <Navigate to={dashboardPath(user)} replace />;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    setError("");
    setSubmitting(true);

    try {
      const currentUser = await login({
        email: email.trim(),
        password,
      });

      navigate(dashboardPath(currentUser), {
        replace: true,
      });
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to sign in",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-100 px-4 py-10">
      <section className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <p className="text-xl font-bold tracking-tight text-blue-600">
          HireSense
        </p>

        <h1 className="mt-6 text-3xl font-bold tracking-tight text-slate-900">
          Interviewer sign in
        </h1>

        <p className="mt-2 text-sm leading-6 text-slate-600">
          Sign in to manage hiring and conduct interviews.
        </p>

        <ErrorMessage message={error} />

        <form
          onSubmit={handleSubmit}
          className="mt-6 space-y-5"
          aria-busy={submitting}
        >
          <div>
            <label
              htmlFor="email"
              className="block text-sm font-medium text-slate-700"
            >
              Email
            </label>

            <input
              id="email"
              name="email"
              type="email"
              autoComplete="username"
              required
              maxLength={254}
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
              className={inputClassName}
            />
          </div>

          <div>
            <label
              htmlFor="password"
              className="block text-sm font-medium text-slate-700"
            >
              Password
            </label>

            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              maxLength={128}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Enter your password"
              className={inputClassName}
            />
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>

      </section>
    </main>
  );
}

import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-100 px-4 py-10">
      <section className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm">
        <p className="text-6xl font-bold text-blue-600">
          404
        </p>

        <h1 className="mt-4 text-2xl font-bold text-slate-900">
          Page not found
        </h1>

        <p className="mt-3 text-sm leading-6 text-slate-600">
          The page you are looking for could not be found.
        </p>

        <Link
          to="/"
          className="mt-6 inline-flex items-center justify-center rounded-lg bg-blue-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
        >
          Go to your dashboard
        </Link>
      </section>
    </main>
  );
}
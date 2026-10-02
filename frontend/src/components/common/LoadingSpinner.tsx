export function LoadingSpinner() {
  return (
    <div
      role="status"
      className="flex min-h-[40vh] items-center justify-center gap-3 px-4"
    >
      <span
        aria-hidden="true"
        className="h-6 w-6 animate-spin rounded-full border-2 border-slate-200 border-t-blue-600 motion-reduce:animate-none"
      />

      <span className="text-sm font-medium text-slate-600">
        Loading…
      </span>
    </div>
  );
}
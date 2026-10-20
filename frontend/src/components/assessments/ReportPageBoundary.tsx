import { Component, type ReactNode } from "react";
import { Link } from "react-router-dom";

/** Keep an unexpected report/chunk error from unmounting the whole application. */
export class ReportPageBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return <section role="alert" className="mx-auto max-w-3xl px-4 py-8">
      <h1 className="text-2xl font-bold">Reports could not be displayed</h1>
      <p className="mt-3 text-slate-600">Your saved reports have not been changed. Reload to try again.</p>
      <div className="mt-4 flex flex-wrap items-center gap-4">
        <button className="rounded-lg bg-blue-600 px-4 py-2 font-semibold text-white" onClick={() => window.location.reload()}>Reload Reports</button>
        <Link className="text-blue-700 underline" to="/interviewer/assessments">Back to candidate ranking</Link>
      </div>
    </section>;
  }
}

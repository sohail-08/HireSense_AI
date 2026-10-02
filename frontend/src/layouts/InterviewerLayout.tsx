import { Outlet } from "react-router-dom";
import { Navbar } from "../components/common/Navbar";

export function InterviewerLayout() {
  return (
    <div className="min-h-screen bg-slate-100 text-slate-900">
      <Navbar />

      <main>
        <Outlet />
      </main>

      {/* Mount the persistent interviewer-only Copilot here later.
          It will remain available across all interviewer pages. */}
    </div>
  );
}
import { Outlet } from "react-router-dom";
import { Navbar } from "../components/common/Navbar";
import { SupervisorProvider } from "../components/assistant/SupervisorProvider";
import { WorkflowReveal } from "../components/assistant/WorkflowReveal";

export function InterviewerLayout() {
  return (
    <SupervisorProvider>
      <WorkflowReveal />
      <div className="interviewer-shell min-h-screen bg-slate-100 text-slate-900">
        <Navbar />
        <main className="interviewer-main">
          <Outlet />
        </main>
      </div>
    </SupervisorProvider>
  );
}

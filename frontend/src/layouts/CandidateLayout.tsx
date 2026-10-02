import { Outlet } from "react-router-dom";
import { Navbar } from "../components/common/Navbar";

export function CandidateLayout() {
  return (
    <div className="min-h-screen bg-slate-100 text-slate-900">
      <Navbar />

      <main>
        <Outlet />
      </main>
    </div>
  );
}
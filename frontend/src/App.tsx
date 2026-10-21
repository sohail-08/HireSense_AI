import {
  Navigate,
  Route,
  Routes,
} from "react-router-dom";
import { lazy, Suspense } from "react";

import {
  dashboardPath,
  useAuth,
} from "./auth/AuthProvider";

import { ProtectedRoute } from "./auth/ProtectedRoute";
import { LoadingSpinner } from "./components/common/LoadingSpinner";

import { CandidateLayout } from "./layouts/CandidateLayout";
import { InterviewerLayout } from "./layouts/InterviewerLayout";

import { CandidateDashboard } from "./pages/CandidateDashboard";
import { CandidatesPage } from "./pages/CandidatesPage";
import { InterviewerDashboard } from "./pages/InterviewerDashboard";
import { InterviewsPage } from "./pages/InterviewsPage";
import { ScheduleInterviewsPage } from "./pages/ScheduleInterviewsPage";
const CandidateInterviewPage = lazy(() => import("./pages/CandidateInterviewPage").then((module) => ({ default: module.CandidateInterviewPage })));
const InterviewerConsolePage = lazy(() => import("./pages/InterviewerConsolePage").then((module) => ({ default: module.InterviewerConsolePage })));
import { JobDescriptionPage } from "./pages/JobDescriptionPage";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { ScreeningPage } from "./pages/ScreeningPage";
import { ReportPageBoundary } from "./components/assessments/ReportPageBoundary";
const ConsolidatedAssessmentsPage = lazy(() => import("./pages/ConsolidatedAssessmentsPage").then(module => ({ default: module.ConsolidatedAssessmentsPage })));
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { NotFoundPage } from "./pages/NotFoundPage";

function HomeRedirect() {
  const { user, loading } = useAuth();

  if (loading) {
    return <LoadingSpinner />;
  }

  return (
    <Navigate
      to={user ? dashboardPath(user) : "/login"}
      replace
    />
  );
}

export default function App() {
  return (
    <Suspense fallback={<LoadingSpinner />}><Routes>
      <Route path="/interview/join/:token" element={<CandidateInterviewPage />} />
      <Route path="/interview/join" element={<CandidateInterviewPage />} />
      <Route
        path="/"
        element={<HomeRedirect />}
      />

      <Route
        path="/login"
        element={<LoginPage />}
      />

      <Route
        path="/register"
        element={<RegisterPage />}
      />

      <Route
        element={
          <ProtectedRoute allowedRole="interviewer" />
        }
      >
        <Route path="/interviews/:interviewId/console" element={<InterviewerConsolePage />} />
        <Route
          path="/interviewer"
          element={<InterviewerLayout />}
        >
          <Route
            index
            element={
              <Navigate to="dashboard" replace />
            }
          />

          <Route
            path="dashboard"
            element={<InterviewerDashboard />}
          />

          <Route
            path="jobs"
            element={<JobDescriptionPage />}
          />

          <Route
            path="candidates"
            element={<CandidatesPage />}
          />

          <Route
            path="interviews"
            element={<InterviewsPage />}
          />
          <Route path="schedule-interviews" element={<ScheduleInterviewsPage />} />

          <Route
            path="assessments"
            element={<ScreeningPage />}
          />
          <Route path="reports" element={<ReportPageBoundary><ConsolidatedAssessmentsPage /></ReportPageBoundary>} />
        </Route>
      </Route>

      <Route
        element={
          <ProtectedRoute allowedRole="candidate" />
        }
      >
        <Route
          path="/candidate"
          element={<CandidateLayout />}
        >
          <Route
            index
            element={
              <Navigate to="dashboard" replace />
            }
          />

          <Route
            path="dashboard"
            element={<CandidateDashboard />}
          />

          <Route
            path="interviews"
            element={
              <PlaceholderPage title="My interviews" />
            }
          />
        </Route>
      </Route>

      <Route
        path="*"
        element={<NotFoundPage />}
      />
    </Routes></Suspense>
  );
}

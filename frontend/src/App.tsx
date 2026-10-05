import {
  Navigate,
  Route,
  Routes,
} from "react-router-dom";

import {
  dashboardPath,
  useAuth,
} from "./auth/AuthProvider";

import { ProtectedRoute } from "./auth/ProtectedRoute";
import { LoadingSpinner } from "./components/common/LoadingSpinner";

import { CandidateLayout } from "./layouts/CandidateLayout";
import { InterviewerLayout } from "./layouts/InterviewerLayout";

import { CandidateDashboard } from "./pages/CandidateDashboard";
import { InterviewerDashboard } from "./pages/InterviewerDashboard";
import { JobDescriptionPage } from "./pages/JobDescriptionPage";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
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
    <Routes>
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
            element={
              <PlaceholderPage title="Candidates" />
            }
          />

          <Route
            path="interviews"
            element={
              <PlaceholderPage title="Interviews" />
            }
          />

          <Route
            path="assessments"
            element={
              <PlaceholderPage title="Assessments" />
            }
          />
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
    </Routes>
  );
}

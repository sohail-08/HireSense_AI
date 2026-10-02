import { Navigate, Outlet } from "react-router-dom";

import {
  dashboardPath,
  useAuth,
} from "./AuthProvider";

import { LoadingSpinner } from "../components/common/LoadingSpinner";
import type { UserRole } from "../types";

export function ProtectedRoute({
  allowedRole,
}: {
  allowedRole: UserRole;
}) {
  const { user, loading } = useAuth();

  if (loading) {
    return <LoadingSpinner />;
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  if (user.role !== allowedRole) {
    return (
      <Navigate
        to={dashboardPath(user)}
        replace
      />
    );
  }

  return <Outlet />;
}
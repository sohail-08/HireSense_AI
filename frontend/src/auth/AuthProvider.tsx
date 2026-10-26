import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import {
  apiRequest,
  AUTH_EXPIRED_EVENT,
  EXPIRY_KEY,
  TOKEN_KEY,
} from "../api/apiClient";

import type {
  LoginRequest,
  TokenResponse,
  User,
} from "../types";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (data: LoginRequest) => Promise<User>;
  logout: () => void;
}

const AuthContext = createContext<
  AuthContextValue | undefined
>(undefined);

export function dashboardPath(user: User): string {
  return user.role === "interviewer" ? "/interviewer/dashboard" : "/login";
}

export function AuthProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const logout = useCallback(() => {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(EXPIRY_KEY);
    setUser(null);
  }, []);

  useEffect(() => {
    let active = true;

    async function restoreSession() {
      if (sessionStorage.getItem(TOKEN_KEY)) {
        try {
          const currentUser = await apiRequest<User>(
            "/auth/me",
          );

          if (active) {
            if (currentUser.role === "interviewer") setUser(currentUser);
            else logout();
          }
        } catch {
          if (active) {
            logout();
          }
        }
      }

      if (active) {
        setLoading(false);
      }
    }

    void restoreSession();

    window.addEventListener(
      AUTH_EXPIRED_EVENT,
      logout,
    );

    return () => {
      active = false;

      window.removeEventListener(
        AUTH_EXPIRED_EVENT,
        logout,
      );
    };
  }, [logout]);

  useEffect(() => {
    if (!user) return;

    const expiresAt = Number(
      sessionStorage.getItem(EXPIRY_KEY),
    );

    const remaining = expiresAt - Date.now();

    if (
      !Number.isFinite(expiresAt) ||
      remaining <= 0
    ) {
      logout();
      return;
    }

    const timer = window.setTimeout(
      logout,
      remaining,
    );

    return () => window.clearTimeout(timer);
  }, [user, logout]);

  async function login(
    data: LoginRequest,
  ): Promise<User> {
    const token = await apiRequest<TokenResponse>(
      "/auth/login",
      {
        method: "POST",
        body: JSON.stringify(data),
      },
      false,
    );

    sessionStorage.setItem(
      TOKEN_KEY,
      token.access_token,
    );

    sessionStorage.setItem(
      EXPIRY_KEY,
      String(Date.now() + token.expires_in * 1000),
    );

    try {
      const currentUser = await apiRequest<User>(
        "/auth/me",
      );

      if (currentUser.role !== "interviewer") throw new Error("Candidates join using their private interview link. No account or sign-in is needed.");
      setUser(currentUser);
      return currentUser;
    } catch (error) {
      logout();
      throw error;
    }
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);

  if (!context) {
    throw new Error(
      "useAuth must be used inside AuthProvider",
    );
  }

  return context;
}

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, clearSession, getStoredUser, getToken, storeSession, type PeriodStatus, type Role, type User } from "../api";

type AuthState = {
  user: User | null;
  login: (username: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
};

const AuthCtx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => (getToken() ? getStoredUser() : null));
  const qc = useQueryClient();

  // Refresh the stored user (role may have changed) once per load.
  useEffect(() => {
    if (!getToken()) return;
    api
      .me()
      .then((u) => {
        setUser(u);
        const t = getToken();
        if (t) storeSession(t, u);
      })
      .catch(() => {});
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const r = await api.login(username, password);
    storeSession(r.token, r.user);
    setUser(r.user);
    return r.user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      /* ignore */
    }
    clearSession();
    qc.clear();
    setUser(null);
  }, [qc]);

  const value = useMemo(() => ({ user, login, logout }), [user, login, logout]);
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(AuthCtx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

export function useUser(): User {
  const { user } = useAuth();
  if (!user) throw new Error("No signed-in user");
  return user;
}

export function RequireAuth({ children, role }: { children: ReactNode; role?: Role }) {
  const { user } = useAuth();
  const loc = useLocation();
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  if (role === "admin" && user.role !== "admin") return <Navigate to="/" replace />;
  return <>{children}</>;
}

export const ROLE_LABEL: Record<Role, string> = { admin: "Admin", reviewer: "Reviewer", preparer: "Preparer" };

/** What the signed-in user can do; each entry is null when allowed, or the reason it isn't. */
export function permissions(user: User, status: PeriodStatus | undefined) {
  const isReviewer = user.role === "reviewer" || user.role === "admin";
  const editable = status === "reconciled" || status === "in_review";
  const notReviewer = "Only a reviewer or admin can do this.";
  return {
    isReviewer,
    isAdmin: user.role === "admin",
    decide: editable
      ? null
      : status === "approved" || status === "closed"
        ? `Decisions are locked: the month is ${status === "closed" ? "closed" : "approved"}. A reviewer can reopen it.`
        : status === "files_uploaded"
          ? "Files changed or the month isn't reconciled yet. Reconcile to edit decisions."
          : "Reconcile the month first.",
    upload: status === "approved" || status === "closed" ? "The month is locked. Reopen it to change files." : null,
    reconcile:
      status === "approved" || status === "closed"
        ? "The month is locked. Reopen it to reconcile again."
        : status === "not_started" || status === undefined
          ? "Upload the purchase register and 2B first."
          : null,
    submit: status === "reconciled" ? null : status === "in_review" ? "Already submitted for review." : "Reconcile the month first.",
    approve: !isReviewer ? notReviewer : status === "in_review" ? null : "The preparer has to submit the month for review first.",
    sendBack: !isReviewer ? notReviewer : status === "in_review" || status === "approved" ? null : "Nothing to send back yet.",
    close: !isReviewer ? notReviewer : status === "approved" ? null : "Approve the month before closing it.",
    reopen: !isReviewer ? notReviewer : status === "approved" || status === "closed" || status === "in_review" ? null : "The month is already open.",
  };
}

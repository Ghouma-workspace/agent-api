import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";

export function RequireAuth({ children }: { children: ReactNode }) {
  const token = localStorage.getItem("access_token");
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}
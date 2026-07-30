import type { AdminSummary, ChatMessage, Conversation, SendMessageResponse, ToolInfo } from "../types";

const BASE_URL = "/api";

function authHeaders(): HeadersInit {
  const token = localStorage.getItem("access_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...init?.headers,
    },
  });
  if (response.status === 401 && !path.startsWith("/auth/")) {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    if (window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
    throw new Error("Session expired, please sign in again");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed: ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string; refresh_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  register: (email: string, password: string) =>
    request<{ id: string; email: string }>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  sendMessage: (content: string, conversationId?: string) =>
    request<SendMessageResponse>("/chat", {
      method: "POST",
      body: JSON.stringify({ content, conversation_id: conversationId ?? null }),
    }),

  listConversations: () => request<Conversation[]>("/conversations"),

  listMessages: (conversationId: string) =>
    request<ChatMessage[]>(`/conversations/${conversationId}/messages`),

  listTools: () => request<ToolInfo[]>("/tools"),

  adminSummary: () => request<AdminSummary>("/admin/summary"),
};

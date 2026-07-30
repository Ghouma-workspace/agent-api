export interface ChatMessage {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  created_at: string;
}

export interface Conversation {
  id: string;
  user_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface SendMessageResponse {
  conversation_id: string;
  message_id: string;
  role: string;
  content: string;
  trace_id: string;
  duration_ms: number;
  node_path: string[];
}

export interface ToolInfo {
  name: string;
  description: string;
}

export interface AdminSummary {
  daily_cost_usd: number;
  active_users: number;
  tool_health: Record<string, boolean>;
}

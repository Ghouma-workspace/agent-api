import type { ChatMessage } from "../../types";

export function MessageList({ messages }: { messages: ChatMessage[] }) {
  return (
    <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
      {messages.map((m) => (
        <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
          <div
            className={`max-w-2xl rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
              m.role === "user"
                ? "bg-accent text-white rounded-br-sm"
                : "bg-white/5 text-gray-100 rounded-bl-sm"
            }`}
          >
            {m.content}
          </div>
        </div>
      ))}
    </div>
  );
}

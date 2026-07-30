import { useState } from "react";
import { ConversationSidebar } from "../components/layout/ConversationSidebar";
import { MessageComposer } from "../components/chat/MessageComposer";
import { MessageList } from "../components/chat/MessageList";
import { TraceTimeline } from "../components/chat/TraceTimeline";
import { useMessages, useSendMessage } from "../hooks/useChat";
import type { SendMessageResponse } from "../types";

export function ChatPage() {
  const [activeId, setActiveId] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<SendMessageResponse | null>(null);
  const { data: messages = [] } = useMessages(activeId);
  const sendMessage = useSendMessage();

  const handleSend = (content: string) => {
    sendMessage.mutate(
      { content, conversationId: activeId ?? undefined },
      {
        onSuccess: (result) => {
          setActiveId(result.conversation_id);
          setLastResult(result);
        },
      }
    );
  };

  return (
    <div className="flex h-screen">
      <ConversationSidebar
        activeId={activeId}
        onSelect={setActiveId}
        onNew={() => {
          setActiveId(null);
          setLastResult(null);
        }}
      />
      <div className="flex flex-1 flex-col">
        <header className="border-b border-white/10 px-6 py-3 text-sm text-gray-400 flex items-center justify-between">
          <span>AI API Assistant</span>
          <button
            onClick={() => {
              localStorage.removeItem("access_token");
              localStorage.removeItem("refresh_token");
              window.location.href = "/login";
            }}
            className="text-xs text-gray-500 hover:text-gray-300"
          >
            Sign out
          </button>
        </header>
        <MessageList messages={messages} />
        {lastResult && <TraceTimeline result={lastResult} />}
        <MessageComposer onSend={handleSend} disabled={sendMessage.isPending} />
      </div>
    </div>
  );
}

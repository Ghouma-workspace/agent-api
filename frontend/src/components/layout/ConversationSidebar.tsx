import { useConversations } from "../../hooks/useChat";

interface Props {
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}

export function ConversationSidebar({ activeId, onSelect, onNew }: Props) {
  const { data: conversations, isLoading } = useConversations();

  return (
    <aside className="w-64 shrink-0 border-r border-white/10 bg-panel flex flex-col">
      <div className="p-3">
        <button
          onClick={onNew}
          className="w-full rounded-md bg-accent/90 hover:bg-accent text-sm font-medium py-2 transition"
        >
          + New conversation
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-2 space-y-1">
        {isLoading && <p className="text-xs text-gray-500 px-2">Loading…</p>}
        {conversations?.map((c) => (
          <button
            key={c.id}
            onClick={() => onSelect(c.id)}
            className={`w-full text-left truncate rounded-md px-3 py-2 text-sm transition ${
              c.id === activeId ? "bg-white/10 text-white" : "text-gray-400 hover:bg-white/5"
            }`}
          >
            {c.title}
          </button>
        ))}
      </div>
    </aside>
  );
}

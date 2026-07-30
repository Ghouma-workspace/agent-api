import { useState } from "react";

interface Props {
  onSend: (content: string) => void;
  disabled?: boolean;
}

export function MessageComposer({ onSend, disabled }: Props) {
  const [value, setValue] = useState("");

  const submit = () => {
    if (!value.trim() || disabled) return;
    onSend(value.trim());
    setValue("");
  };

  return (
    <div className="border-t border-white/10 p-4">
      <div className="flex items-end gap-2 rounded-xl bg-panel border border-white/10 px-3 py-2">
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          rows={1}
          placeholder="Ask me to create a GitHub issue, check the weather, list your repos…"
          className="flex-1 resize-none bg-transparent text-sm outline-none placeholder:text-gray-500"
        />
        <button
          onClick={submit}
          disabled={disabled}
          className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium disabled:opacity-50"
        >
          Send
        </button>
      </div>
    </div>
  );
}

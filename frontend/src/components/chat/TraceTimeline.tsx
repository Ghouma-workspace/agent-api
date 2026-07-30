import { useState } from "react";
import type { SendMessageResponse } from "../../types";

export function TraceTimeline({ result }: { result: SendMessageResponse }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="mx-6 mb-3 rounded-lg border border-white/10 bg-panel/60 text-xs text-gray-400">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2 hover:text-gray-200 transition"
      >
        <span className="flex items-center gap-3">
          <span>⏱ {result.duration_ms.toFixed(0)} ms</span>
          <span className="font-mono text-gray-500">trace: {result.trace_id.slice(0, 12)}…</span>
        </span>
        <span>{expanded ? "▲ hide reasoning" : "▼ show reasoning"}</span>
      </button>
      {expanded && (
        <ol className="px-4 pb-3 space-y-1">
          {result.node_path.map((node, i) => (
            <li key={i} className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-accent" />
              <span className="font-mono">{node}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

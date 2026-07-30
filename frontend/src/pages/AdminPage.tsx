import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export function AdminPage() {
  const { data } = useQuery({ queryKey: ["admin-summary"], queryFn: api.adminSummary });

  return (
    <div className="p-8 space-y-6">
      <h1 className="text-xl font-semibold">Admin dashboard</h1>
      <div className="grid grid-cols-3 gap-4">
        <div className="rounded-lg bg-panel border border-white/10 p-4">
          <p className="text-xs text-gray-500">Daily LLM cost</p>
          <p className="text-2xl font-semibold mt-1">${data?.daily_cost_usd.toFixed(4) ?? "—"}</p>
        </div>
        <div className="rounded-lg bg-panel border border-white/10 p-4">
          <p className="text-xs text-gray-500">Active users</p>
          <p className="text-2xl font-semibold mt-1">{data?.active_users ?? "—"}</p>
        </div>
        <div className="rounded-lg bg-panel border border-white/10 p-4 col-span-1">
          <p className="text-xs text-gray-500 mb-2">Tool health</p>
          <ul className="space-y-1 text-sm">
            {data &&
              Object.entries(data.tool_health).map(([name, healthy]) => (
                <li key={name} className="flex items-center justify-between">
                  <span>{name}</span>
                  <span className={healthy ? "text-emerald-400" : "text-red-400"}>
                    {healthy ? "● healthy" : "● down"}
                  </span>
                </li>
              ))}
          </ul>
        </div>
      </div>
      <p className="text-xs text-gray-500">
        Historical latency, request-rate, and cost trends live in Grafana at
        <span className="font-mono"> :3000</span> — this page surfaces current-state numbers only.
      </p>
    </div>
  );
}

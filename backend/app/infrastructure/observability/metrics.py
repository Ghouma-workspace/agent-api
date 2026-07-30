"""Single source of truth for every Prometheus metric. Import these, never
instantiate a Counter/Histogram anywhere else, or Prometheus will register duplicates."""
from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "path", "status"]
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "path"]
)

AGENT_NODE_DURATION_SECONDS = Histogram(
    "agent_node_duration_seconds", "LangGraph node execution latency", ["node"]
)

TOOL_EXECUTION_DURATION_SECONDS = Histogram(
    "tool_execution_duration_seconds", "Tool call latency", ["tool_name", "success"]
)
TOOL_EXECUTIONS_TOTAL = Counter(
    "tool_executions_total", "Total tool executions", ["tool_name", "success"]
)

LLM_REQUEST_DURATION_SECONDS = Histogram(
    "llm_request_duration_seconds", "LLM completion latency", ["provider", "model"]
)
LLM_PROMPT_TOKENS_TOTAL = Counter(
    "llm_prompt_tokens_total", "Total prompt tokens consumed", ["provider", "model"]
)
LLM_COMPLETION_TOKENS_TOTAL = Counter(
    "llm_completion_tokens_total", "Total completion tokens generated", ["provider", "model"]
)
LLM_COST_USD_TOTAL = Counter("llm_cost_usd_total", "Total estimated LLM spend in USD", ["model"])

CACHE_HITS_TOTAL = Counter("cache_hits_total", "Cache hits", ["cache_name"])
CACHE_MISSES_TOTAL = Counter("cache_misses_total", "Cache misses", ["cache_name"])

RETRIES_TOTAL = Counter("retries_total", "Total retry attempts", ["component"])
FAILURES_TOTAL = Counter("failures_total", "Total unrecoverable failures", ["component"])

ACTIVE_USERS = Gauge("active_users", "Users with activity in the last 5 minutes")

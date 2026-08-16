"""Single source of truth for every Prometheus metric.

HTTP request metrics (http_requests_total, http_request_duration_seconds) are
created automatically by prometheus_fastapi_instrumentator — do NOT define them
here or you get a duplicate registration conflict that silently zeroes both.
"""

from prometheus_client import Counter, Gauge, Histogram

AGENT_NODE_DURATION_SECONDS = Histogram(
    "agent_node_duration_seconds",
    "LangGraph node execution latency in seconds",
    ["node"],
)

TOOL_EXECUTION_DURATION_SECONDS = Histogram(
    "tool_execution_duration_seconds",
    "Tool call latency in seconds",
    ["tool_name", "success"],
)
TOOL_EXECUTIONS_TOTAL = Counter(
    "tool_executions_total",
    "Total tool executions",
    ["tool_name", "success"],
)

LLM_REQUEST_DURATION_SECONDS = Histogram(
    "llm_request_duration_seconds",
    "LLM completion latency in seconds",
    ["provider", "model"],
)
LLM_PROMPT_TOKENS_TOTAL = Counter(
    "llm_prompt_tokens_total",
    "Total prompt tokens consumed",
    ["provider", "model"],
)
LLM_COMPLETION_TOKENS_TOTAL = Counter(
    "llm_completion_tokens_total",
    "Total completion tokens generated",
    ["provider", "model"],
)
LLM_COST_USD_TOTAL = Counter(
    "llm_cost_usd_total",
    "Total estimated LLM spend in USD",
    ["model"],
)

CACHE_HITS_TOTAL = Counter("cache_hits_total", "Cache hits", ["cache_name"])
CACHE_MISSES_TOTAL = Counter("cache_misses_total", "Cache misses", ["cache_name"])

RETRIES_TOTAL = Counter("retries_total", "Total retry attempts", ["component"])
FAILURES_TOTAL = Counter("failures_total", "Total unrecoverable failures", ["component"])

ACTIVE_USERS = Gauge("active_users", "Users with activity in the last 5 minutes")

CIRCUIT_BREAKER_STATE = Gauge(
    "circuit_breaker_state",
    "Circuit breaker state per tool (0=CLOSED, 1=HALF_OPEN, 2=OPEN)",
    ["tool_name"],
)

CONTENT_FILTER_TRIGGERS_TOTAL = Counter(
    "content_filter_triggers_total",
    "Total content filter trigger events",
)
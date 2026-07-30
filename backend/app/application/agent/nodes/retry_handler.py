import asyncio

from app.application.agent.state import AgentState
from app.infrastructure.observability.agent_tracing import traced_node
from app.infrastructure.observability.metrics import RETRIES_TOTAL


def make_retry_handler(max_retries: int):
    @traced_node("retry_handler")
    async def retry_handler(state: AgentState) -> dict:
        RETRIES_TOTAL.labels(component="tool_executor").inc()
        backoff_seconds = min(2**state.retry_count * 0.25, 4.0)
        await asyncio.sleep(backoff_seconds)
        return {"retry_count": state.retry_count + 1}

    return retry_handler

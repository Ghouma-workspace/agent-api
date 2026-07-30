from langfuse import Langfuse

from app.core.config import Settings


def create_langfuse_client(settings: Settings) -> Langfuse | None:
    if not settings.langfuse_public_key.get_secret_value():
        return None
    return Langfuse(
        public_key=settings.langfuse_public_key.get_secret_value(),
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        host=settings.langfuse_host,
    )


class LangfuseTracker:
    def __init__(self, client: Langfuse | None) -> None:
        self._client = client

    def start_trace(self, *, name: str, user_id: str, session_id: str, trace_id: str):
        """One root trace per chat turn. Every agent node nests a child observation
        under the object this returns — see agent_tracing.py's traced_node()."""
        if self._client is None:
            return None
        return self._client.trace(name=name, user_id=user_id, session_id=session_id, id=trace_id)

    def score(self, trace_id: str, *, name: str, value: float, comment: str | None = None) -> None:
        if self._client is None:
            return
        self._client.score(trace_id=trace_id, name=name, value=value, comment=comment)

    def flush(self) -> None:
        if self._client is not None:
            self._client.flush()

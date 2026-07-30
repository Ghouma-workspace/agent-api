from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.entities.chat import ChatMessage, ToolCall, ToolResult


class AgentState(BaseModel):
    """Flows through every LangGraph node. Immutable-by-convention: nodes return a
    partial dict of updates (LangGraph merges it), rather than mutating in place."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    conversation_id: UUID
    user_id: UUID
    trace_id: str
    messages: list[ChatMessage] = Field(default_factory=list)

    needs_tool: bool = False
    selected_tool: ToolCall | None = None
    tool_result: ToolResult | None = None

    draft_response: str = ""
    validation_errors: list[str] = Field(default_factory=list)

    retry_count: int = 0
    validation_loop_count: int = 0
    error: str | None = None
    node_path: list[str] = Field(default_factory=list)

    prompt_tokens: int = 0
    completion_tokens: int = 0

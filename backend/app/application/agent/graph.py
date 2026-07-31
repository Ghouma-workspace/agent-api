from langgraph.graph import END, StateGraph

from app.application.agent.nodes.error_handler import error_handler
from app.application.agent.nodes.planner import make_planner
from app.application.agent.nodes.response_generator import make_response_generator
from app.application.agent.nodes.retry_handler import make_retry_handler
from app.application.agent.nodes.tool_executor import make_tool_executor
from app.application.agent.nodes.tool_selector import make_tool_selector
from app.application.agent.nodes.validator import validator
from app.application.agent.state import AgentState
from app.core.config import Settings
from app.domain.providers.interfaces import LLMProvider, ToolRegistry


def _route_after_planner(state: AgentState) -> str:
    if state.needs_tool and state.selected_tool is not None:
        return "tool_executor"
    return "response_generator"


def _route_after_selector(state: AgentState) -> str:
    return "tool_executor" if state.selected_tool is not None else "response_generator"


def _route_after_executor(state: AgentState) -> str:
    return (
        "response_generator" if state.tool_result and state.tool_result.success else "error_handler"
    )


def _route_after_error_handler(state: AgentState, max_retries: int) -> str:
    if state.error == "retryable" and state.retry_count < max_retries:
        return "retry_handler"
    return "response_generator"


def _route_after_validator(state: AgentState, max_loops: int) -> str:
    if state.validation_errors and state.validation_loop_count < max_loops:
        return "tool_selector"
    return END


def build_agent_graph(llm: LLMProvider, tool_registry: ToolRegistry, settings: Settings):
    """Wires the full graph described in ARCHITECTURE.md section 5. Returns a compiled
    LangGraph runnable that ChatService.invoke()s per conversation turn."""
    graph = StateGraph(AgentState)

    graph.add_node("planner", make_planner(llm, tool_registry))
    graph.add_node("tool_selector", make_tool_selector(llm, tool_registry))
    graph.add_node("tool_executor", make_tool_executor(tool_registry))
    graph.add_node("response_generator", make_response_generator(llm))
    graph.add_node("validator", validator)
    graph.add_node("error_handler", error_handler)
    graph.add_node("retry_handler", make_retry_handler(settings.agent_max_tool_retries))

    graph.set_entry_point("planner")

    graph.add_conditional_edges(
        "planner",
        _route_after_planner,
        {"tool_executor": "tool_executor", "response_generator": "response_generator"},
    )
    graph.add_conditional_edges(
        "tool_selector",
        _route_after_selector,
        {"tool_executor": "tool_executor", "response_generator": "response_generator"},
    )
    graph.add_conditional_edges(
        "tool_executor",
        _route_after_executor,
        {"response_generator": "response_generator", "error_handler": "error_handler"},
    )
    graph.add_conditional_edges(
        "error_handler",
        lambda s: _route_after_error_handler(s, settings.agent_max_tool_retries),
        {"retry_handler": "retry_handler", "response_generator": "response_generator"},
    )
    graph.add_edge("retry_handler", "tool_executor")
    graph.add_edge("response_generator", "validator")
    graph.add_conditional_edges(
        "validator",
        lambda s: _route_after_validator(s, settings.agent_max_validation_loops),
        {"tool_selector": "tool_selector", END: END},
    )

    return graph.compile()

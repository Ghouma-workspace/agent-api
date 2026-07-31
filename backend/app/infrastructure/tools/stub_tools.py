"""Stub plugins. Each demonstrates that adding a tool is just: subclass BaseToolPlugin,
declare name/description/parameters_schema, implement execute(), register it — no
changes anywhere else in the codebase. Wire real credentials + HTTP calls the same
way GitHubTool/WeatherTool do to take these from stub to production."""

from typing import ClassVar

from app.infrastructure.tools.base import BaseToolPlugin, ToolExecutionContext, ToolResultPayload


class JiraTool(BaseToolPlugin):
    name = "jira"
    description = "Create or search Jira tickets."
    parameters_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create_ticket", "search"]},
            "project_key": {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict, ctx: ToolExecutionContext) -> ToolResultPayload:
        return ToolResultPayload(
            success=False,
            error="Jira integration not configured — stub plugin, add JIRA_* credentials",
        )


class NotionTool(BaseToolPlugin):
    name = "notion"
    description = "Search Notion pages."
    parameters_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    async def execute(self, args: dict, ctx: ToolExecutionContext) -> ToolResultPayload:
        return ToolResultPayload(
            success=False, error="Notion integration not configured — stub plugin"
        )


class TrelloTool(BaseToolPlugin):
    name = "trello"
    description = "Create a Trello card."
    parameters_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {"board_id": {"type": "string"}, "title": {"type": "string"}},
        "required": ["board_id", "title"],
    }

    async def execute(self, args: dict, ctx: ToolExecutionContext) -> ToolResultPayload:
        return ToolResultPayload(
            success=False, error="Trello integration not configured — stub plugin"
        )


class SlackTool(BaseToolPlugin):
    name = "slack"
    description = "Post a message to a Slack channel."
    parameters_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {"channel": {"type": "string"}, "text": {"type": "string"}},
        "required": ["channel", "text"],
    }

    async def execute(self, args: dict, ctx: ToolExecutionContext) -> ToolResultPayload:
        return ToolResultPayload(
            success=False, error="Slack integration not configured — stub plugin"
        )


class StripeTool(BaseToolPlugin):
    name = "stripe"
    description = "Summarize recent Stripe payments."
    parameters_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {"limit": {"type": "integer", "default": 10}},
        "required": [],
    }

    async def execute(self, args: dict, ctx: ToolExecutionContext) -> ToolResultPayload:
        return ToolResultPayload(
            success=False, error="Stripe integration not configured — stub plugin"
        )

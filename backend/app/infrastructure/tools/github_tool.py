from typing import ClassVar

from app.infrastructure.tools.base import (
    BaseToolPlugin,
    ResilientHTTPClient,
    ToolExecutionContext,
    ToolResultPayload,
)


class GitHubTool(BaseToolPlugin):
    """Fully implemented reference tool: 'list_repos' and 'create_issue' actions
    against the real GitHub REST API. Demonstrates the plugin contract end-to-end."""

    name = "github"
    description = "List the user's GitHub repositories or create an issue in a repository."
    parameters_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list_repos", "create_issue"]},
            "repo": {"type": "string", "description": "owner/repo, required for create_issue"},
            "title": {"type": "string", "description": "issue title, required for create_issue"},
            "body": {"type": "string", "description": "issue body, optional"},
        },
        "required": ["action"],
    }

    def __init__(self, credentials) -> None:
        super().__init__(credentials)
        self._http = ResilientHTTPClient(base_url="https://api.github.com", timeout=10.0)

    def _headers(self) -> dict:
        token = self._credentials.get_secret("github_token")
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def execute(self, args: dict, ctx: ToolExecutionContext) -> ToolResultPayload:
        action = args.get("action")
        try:
            if action == "list_repos":
                response = await self._http.request(
                    "GET", "/user/repos", headers=self._headers(), params={"per_page": 20}
                )
                repos = [
                    {"name": r["full_name"], "url": r["html_url"], "private": r["private"]}
                    for r in response.json()
                ]
                return ToolResultPayload(success=True, output={"repos": repos})

            if action == "create_issue":
                repo = args.get("repo")
                title = args.get("title")
                if not repo or not title:
                    return ToolResultPayload(
                        success=False, error="'repo' and 'title' are required for create_issue"
                    )
                response = await self._http.request(
                    "POST",
                    f"/repos/{repo}/issues",
                    headers=self._headers(),
                    json={"title": title, "body": args.get("body", "")},
                )
                issue = response.json()
                return ToolResultPayload(
                    success=True, output={"issue_number": issue["number"], "url": issue["html_url"]}
                )

            return ToolResultPayload(success=False, error=f"unknown action '{action}'")
        except Exception as exc:  # httpx.HTTPStatusError, network errors, etc.
            return ToolResultPayload(success=False, error=str(exc))

    async def health_check(self) -> bool:
        try:
            response = await self._http.request("GET", "/rate_limit", headers=self._headers())
            return response.status_code == 200
        except Exception:
            return False

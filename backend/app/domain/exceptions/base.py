"""Domain exceptions carry no HTTP knowledge — the API layer maps them to status codes."""


class DomainError(Exception):
    """Base class for all domain-level errors."""


class NotFoundError(DomainError):
    def __init__(self, entity: str, identifier: str) -> None:
        self.entity = entity
        self.identifier = identifier
        super().__init__(f"{entity} '{identifier}' not found")


class AuthenticationError(DomainError):
    pass


class AuthorizationError(DomainError):
    pass


class ValidationError(DomainError):
    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        self.errors = errors or []
        super().__init__(message)


class RateLimitExceededError(DomainError):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Rate limit exceeded, retry after {retry_after_seconds}s")


class ToolExecutionError(DomainError):
    def __init__(self, tool_name: str, message: str, *, retryable: bool = True) -> None:
        self.tool_name = tool_name
        self.retryable = retryable
        super().__init__(f"Tool '{tool_name}' failed: {message}")


class LLMProviderError(DomainError):
    def __init__(self, provider: str, message: str, *, retryable: bool = True) -> None:
        self.provider = provider
        self.retryable = retryable
        super().__init__(f"LLM provider '{provider}' error: {message}")

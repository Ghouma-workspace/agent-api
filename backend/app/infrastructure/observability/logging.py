import logging
import uuid
from contextvars import ContextVar

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import Settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
user_id_var: ContextVar[str] = ContextVar("user_id", default="")


def _inject_context(logger, method_name, event_dict):
    if rid := request_id_var.get():
        event_dict["request_id"] = rid
    if tid := trace_id_var.get():
        event_dict["trace_id"] = tid
    if uid := user_id_var.get():
        event_dict["user_id"] = uid
    return event_dict


def setup_logging(settings: Settings) -> None:
    logging.basicConfig(level=settings.log_level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _inject_context,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Generates/propagates request_id, extracts the OTel trace_id, and attaches both
    to every structured log line for the duration of the request — this is the thread
    that ties HTTP logs, Jaeger traces, and Langfuse traces together."""

    async def dispatch(self, request: Request, call_next):
        from opentelemetry import trace as otel_trace

        request_id = str(uuid.uuid4())
        request_id_var.set(request_id)
        request.state.request_id = request_id

        span_ctx = otel_trace.get_current_span().get_span_context()
        trace_id = format(span_ctx.trace_id, "032x") if span_ctx.trace_id else request_id
        trace_id_var.set(trace_id)
        request.state.trace_id = trace_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-ID"] = trace_id
        return response

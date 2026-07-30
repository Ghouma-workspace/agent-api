from prometheus_fastapi_instrumentator import Instrumentator

from app.core.config import Settings


def setup_prometheus(app, settings: Settings) -> None:
    """Auto-instruments every route for http_requests_total/http_request_duration_seconds
    and exposes them at settings.prometheus_metrics_path for Prometheus to scrape,
    alongside the custom metrics defined in observability/metrics.py."""
    instrumentator = Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        excluded_handlers=[settings.prometheus_metrics_path],
    )
    instrumentator.instrument(app).expose(app, endpoint=settings.prometheus_metrics_path)

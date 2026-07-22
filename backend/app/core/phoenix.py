"""Phoenix (Arize) observability wiring.

Registers an OpenTelemetry tracer provider that ships traces to a Phoenix
collector, then turns on OpenInference auto-instrumentation for LangChain /
LangGraph. Because instrumentation is applied by patching LangChain's callback
layer, nothing in the agent/business code imports this module — tracing stays
fully decoupled from the code it observes.

Gated on PHOENIX_ENABLED so the app runs identically when it's off, mirroring
the SENTRY_DSN gate in main.py. Any failure here is swallowed: observability
must never take down the API.
"""

from app.core.config import settings
from app.core.logging import logger


def setup_phoenix() -> None:
    if not settings.PHOENIX_ENABLED:
        logger.info("phoenix_disabled", reason="PHOENIX_ENABLED is false")
        return

    try:
        from openinference.instrumentation.langchain import LangChainInstrumentor
        from phoenix.otel import register

        tracer_provider = register(
            project_name=settings.PHOENIX_PROJECT_NAME,
            endpoint=f"{settings.PHOENIX_COLLECTOR_ENDPOINT}/v1/traces",
        )
        LangChainInstrumentor().instrument(tracer_provider=tracer_provider)
        logger.info(
            "phoenix_enabled",
            endpoint=settings.PHOENIX_COLLECTOR_ENDPOINT,
            project=settings.PHOENIX_PROJECT_NAME,
        )
    except Exception as err:  # noqa: BLE001
        logger.error("phoenix_init_failed", error=str(err))

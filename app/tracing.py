"""
phoenix_tracing.py — Arize Phoenix tracing for Vivu agent.

Usage:
    # In your code:
    from app.tracing import setup_tracing
    setup_tracing()

    # Or start Phoenix UI:
    python -m phoenix.server.main serve
    # Then open http://localhost:6006
"""

import logging
import os

logger = logging.getLogger("phoenix.tracing")

_tracer_provider = None


def setup_tracing(project_name: str = "vivu"):
    """Setup Phoenix tracing. Call once at app startup."""
    global _tracer_provider

    if os.environ.get("PHOENIX_ENABLED", "false").lower() != "true":
        logger.info("Phoenix tracing disabled (set PHOENIX_ENABLED=true to enable)")
        return None

    try:
        import phoenix as px
        from phoenix.otel import register
        from openinference.instrumentation.openai import OpenAIInstrumentor

        # Launch Phoenix server
        px.launch_app()
        logger.info("Phoenix UI started at http://localhost:6006")

        # Register tracer provider
        _tracer_provider = register(
            project_name=project_name,
            endpoint="http://localhost:6006/v1/traces",
        )

        # Auto-instrument OpenAI calls
        OpenAIInstrumentor().instrument(tracer_provider=_tracer_provider)

        logger.info("Phoenix tracing enabled for project '%s'", project_name)
        return _tracer_provider

    except ImportError as e:
        logger.warning("Phoenix not installed: %s", e)
        return None
    except Exception as e:
        logger.warning("Phoenix setup failed: %s", e)
        return None


def get_tracer():
    """Get the tracer provider."""
    return _tracer_provider

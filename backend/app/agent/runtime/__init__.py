"""Agent runtime adapters.

FilmOS owns authentication, persistence, and browser SSE. Runtime adapters only
translate a model/agent transport into typed events consumed by the runner.
"""

from app.agent.runtime.base import AgentRuntimeError, RuntimeEvent

__all__ = ["AgentRuntimeError", "RuntimeEvent"]

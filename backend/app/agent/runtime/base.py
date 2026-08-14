from dataclasses import dataclass, field
from typing import Any, Literal


class AgentRuntimeError(RuntimeError):
    """Safe runtime failure that can be shown without leaking upstream details."""

    def __init__(self, message: str = "AI 助手暂时不可用，请稍后重试") -> None:
        super().__init__(message)


@dataclass(slots=True)
class RuntimeEvent:
    type: Literal["delta", "completed"]
    content: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

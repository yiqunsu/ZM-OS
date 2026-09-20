"""Versioned, read-only display contract built from trusted capability results."""

from typing import Literal

from pydantic import BaseModel, Field


class ReplyMetric(BaseModel):
    label: str
    value: int = Field(ge=0)


class ReplyRow(BaseModel):
    label: str
    detail: str


class AgentPresentation(BaseModel):
    version: Literal[1] = 1
    kind: Literal["schedule", "board"]
    title: str
    metrics: list[ReplyMetric]
    rows: list[ReplyRow]
    warnings: list[str] = Field(default_factory=list)
    next_step: str


def schedule_presentation(plan: dict) -> AgentPresentation:
    tasks = plan["tasks"]
    machines: dict[str, int] = {}
    for task in tasks:
        name = task["machine_name"]
        machines[name] = machines.get(name, 0) + 1
    return AgentPresentation(
        kind="schedule", title="排产草案快照",
        metrics=[
            ReplyMetric(label="新任务", value=len(tasks)),
            ReplyMetric(label="已安排订单", value=sum(len(t["order_ids"]) for t in tasks)),
            ReplyMetric(label="未安排", value=len(plan["unassigned"])),
        ],
        rows=[ReplyRow(label=name, detail=f"{count} 个新任务") for name, count in machines.items()],
        warnings=[f"{item['order_no']}：{item['reason']}" for item in plan["unassigned"]],
        next_step="在右侧调整并核对方案，再确认下发。此卡片是回复时的快照，以右侧最新状态为准。",
    )


def board_presentation(board: dict) -> AgentPresentation:
    tasks = [task for machine in board["machines"] for task in machine["tasks"]]
    return AgentPresentation(
        kind="board", title="生产概况快照",
        metrics=[
            ReplyMetric(label="生产中任务", value=sum(t["status"] == "PRODUCING" for t in tasks)),
            ReplyMetric(label="等待任务", value=sum(t["status"] == "WAITING" for t in tasks)),
            ReplyMetric(label="待排订单", value=len(board["pending_orders"])),
        ],
        rows=[ReplyRow(label=m["name"], detail=f"{len(m['tasks'])} 个已下发任务") for m in board["machines"]],
        next_step="这是查询时的生产快照；实时队列请查看生产看板。",
    )

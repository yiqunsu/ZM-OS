"""In-process capability adapter; trusted identity never comes from model arguments."""

from typing import Any

from fastapi import HTTPException

from app.core.database import async_session
from app.models import ChatSession
from app.services import chat_service, kanban_service, schedule_service


class SchedulingAdapter:
    def __init__(self, session_id: str, user_id: str) -> None:
        self.session_id = session_id
        self.user_id = user_id
        self.events: list[dict[str, Any]] = []
        self.generated: dict[str, Any] | None = None

    async def invoke(self, name: str) -> dict[str, Any]:
        async with async_session() as db:
            await chat_service.require_session(db, self.session_id, self.user_id)
            try:
                if name == "read_board":
                    return (await kanban_service.get_kanban(db)).model_dump(mode="json")
                if name == "read_draft":
                    plan = await schedule_service.get_latest_draft(db, self.session_id, self.user_id)
                    return schedule_service.plan_payload(plan) if plan else {"message": "暂无草案"}
                if name == "generate_draft":
                    if self.generated is not None:
                        return self.generated
                    plan = await schedule_service.create_schedule_plan(db, self.session_id, self.user_id)
                    session = await db.get(ChatSession, self.session_id)
                    session.active_workspace = "schedule_plan"
                    session.workspace_state = None
                    await db.commit()
                    self.generated = schedule_service.plan_payload(plan)
                    self.events.extend([
                        {"type": "panel", "panel": "schedule_plan", "action": "open"},
                        {"type": "schedule_plan", "plan": self.generated},
                    ])
                    return self.generated
                return {"error": "未知工具"}
            except HTTPException as exc:
                await db.rollback()
                return {"error": str(exc.detail)}

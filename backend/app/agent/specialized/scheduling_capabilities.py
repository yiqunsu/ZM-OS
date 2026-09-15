"""Read-only business tools plus authorized proposal generation for scheduling."""

import json

from fastapi import HTTPException
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError
from sqlalchemy import select

from app.agent.model_transport import content_text
from app.agent.specialized import prompts
from app.agent.specialized.admission import Admission
from app.agent.specialized.model_io import ModelIO
from app.agent.worker import LeaseLost, lock_run
from app.models import AgentRun, ChatMessage, ChatSession, SchedulePlan
from app.schemas.agent import AgentInput
from app.services import agent_schedule_service as plans
from app.services import kanban_service, schedule_service
from app.services.agent_event_service import append_event
from app.services.agent_tool_service import perform_tool
from app.services.scheduling_lock import lock_scheduling_inputs

TOOL_NAMES = frozenset({"read_board", "read_draft", "generate_draft"})
TOOLS = [
    {
        "type": "function",
        "function": {"name": name, "description": desc, "parameters": AgentInput.model_json_schema()},
    }
    for name, desc in (
        ("read_board", "查询实际机器队列和待排订单统计"),
        ("read_draft", "读取本会话最新草案及过期状态"),
        ("generate_draft", "仅在本轮已授权生成时准备草案，不能执行排产"),
    )
]


def compact_plan(plan: SchedulePlan | dict | None) -> dict:
    if plan is None:
        return {"plan": None}
    get = plan.get if isinstance(plan, dict) else lambda key, default=None: getattr(plan, key, default)
    tasks, unassigned = get("tasks", []), get("unassigned", [])
    return {
        "id": get("id"),
        "revision": get("revision"),
        "status": get("status"),
        "task_count": len(tasks),
        "load_basis": get("load_basis") or get("input_fingerprint", {}).get("__load_basis__", "WEIGHT_KG"),
        "assigned_order_count": sum(len(task["order_ids"]) for task in tasks),
        "unassigned_count": len(unassigned),
        "unassigned_examples": [
            {"order_no": row.get("order_no"), "reason": str(row.get("reason", ""))[:150]}
            for row in unassigned[:10]
        ],
        "machine_examples": [
            {
                "machine": task["machine_name"],
                "orders": len(task["order_ids"]),
                "reason": str(task.get("reason", ""))[:150],
            }
            for task in tasks[:10]
        ],
        "examples_truncated": len(tasks) > 10 or len(unassigned) > 10,
    }


class SchedulingCapabilities(ModelIO):
    async def load(self):
        async with self.sessions() as db:
            session, run = await lock_run(db, self.context)
            rows = (
                await db.scalars(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == session.id, ChatMessage.event_seq <= run.input_event_seq)
                    .order_by(ChatMessage.event_seq.desc())
                    .limit(30)
                )
            ).all()
            messages, used_ids, size = [], [], 0
            for row in rows:
                content = (row.content or "")[:2000]
                if size + len(content.encode()) > 7000:
                    break
                messages.append(
                    AIMessage(content=content) if row.role == "assistant" else HumanMessage(content=content)
                )
                used_ids.append(row.id)
                size += len(content.encode())
            messages.reverse()
            plan = await db.get(SchedulePlan, session.active_plan_id) if session.active_plan_id else None
            trigger = await db.get(ChatMessage, run.trigger_message_id) if run.trigger_message_id else None
            loaded = {
                "messages": messages,
                "input_text": (trigger.content or "") if trigger else "",
                "trigger_kind": run.trigger_kind,
                "workbench": run.config_snapshot.get("scheduling_workbench", False),
                "retry_intent": run.config_snapshot.get("retry_intent"),
                "plan": compact_plan(plan),
            }
            run.context_snapshot = {
                "schema_version": 1,
                "message_ids": list(reversed(used_ids)),
                "plan_id": plan.id if plan else None,
                "plan_revision": plan.revision if plan else None,
                "input_event_seq": run.input_event_seq,
                "truncated_message_count": len(rows) - len(messages),
                "usage_complete": True,
            }
            await db.commit()
            self.loaded = loaded
            self.generation_allowed = loaded["workbench"]
            return loaded

    async def admit(self, loaded):
        if loaded["trigger_kind"] == "REPLACE_PLAN" or loaded["retry_intent"]:
            admission = Admission(decision="ALLOW", reason_code="IN_SCOPE", requested_operation="GENERATE")
        else:
            admission = await self.admit_input(
                {
                    "agent_type": "SCHEDULING",
                    "input": loaded["input_text"][:2000],
                    "plan": loaded["plan"],
                }
            )
        self.generation_allowed = (
            admission.decision == "ALLOW" and admission.requested_operation == "GENERATE"
        )
        async with self.sessions() as db:
            session, run = await lock_run(db, self.context)
            append_event(db, session, "admittance.decided", admission.model_dump(), run_id=run.id)
            await db.commit()
        return admission.model_dump()

    async def _current_plan(self):
        async with self.sessions() as db:
            session, _ = await lock_run(db, self.context)
            await lock_scheduling_inputs(db)
            plan = await db.get(SchedulePlan, session.active_plan_id) if session.active_plan_id else None
            return {
                **compact_plan(plan),
                "stale": await schedule_service.plan_is_stale(db, plan) if plan else False,
            }

    async def generate(self):
        return await self.tool({"id": "generate_draft", "name": "generate_draft", "args": {}})

    async def tool(self, call):
        name = call.get("name")
        if name not in TOOL_NAMES or call.get("args"):
            return {"error_code": "TOOL_NOT_ALLOWED"}
        if name == "generate_draft" and not self.generation_allowed:
            return {"error_code": "GENERATION_NOT_AUTHORIZED"}

        async def operation(db):
            session = await db.get(ChatSession, self.context.session_id)
            run = await db.get(AgentRun, self.context.run_id)
            if name == "generate_draft":
                result = await plans.generate(db, session, run)
                if "id" not in result:
                    return result
                return {
                    **compact_plan(result),
                    "outcome": result.get("outcome", "DRAFT_READY"),
                    "replacement_required": result.get("replacement_required", False),
                }
            await lock_scheduling_inputs(db)
            if name == "read_draft":
                plan = await db.get(SchedulePlan, session.active_plan_id) if session.active_plan_id else None
                return {
                    **compact_plan(plan),
                    "stale": await schedule_service.plan_is_stale(db, plan) if plan else False,
                }
            board = (await kanban_service.get_kanban(db)).model_dump(mode="json")
            return {
                "pending_order_count": len(board["pending_orders"]),
                "machine_count": len(board["machines"]),
                "machines": [
                    {"name": machine["name"], "task_count": len(machine["tasks"])}
                    for machine in board["machines"][:20]
                ],
                "examples_truncated": len(board["machines"]) > 20,
            }

        try:
            return await perform_tool(
                self.sessions,
                self.context,
                call_key=call["id"],
                tool_name=name,
                args={},
                allowed_tools=TOOL_NAMES,
                operation=operation,
            )
        except LeaseLost:
            raise
        except (ValidationError, HTTPException) as error:
            return {
                "error_code": error.detail.get("code", "TOOL_FAILED")
                if isinstance(error, HTTPException) and isinstance(error.detail, dict)
                else "TOOL_FAILED"
            }

    async def main(self, messages, loaded):
        await self.count_model("READING_BOARD")
        model = await self._model()
        if self.bound_model is None:
            self.bound_model = model.bind_tools(TOOLS, parallel_tool_calls=False)
        facts = json.dumps(
            {"plan": await self._current_plan(), "generation_authorized": self.generation_allowed},
            ensure_ascii=False,
        )
        reply = await self.bound_model.ainvoke(
            self.bounded_messages(prompts.SCHEDULING_SKILL + facts, messages)
        )
        await self.usage(reply)
        return reply

    async def compose(self, messages, loaded):
        await self.count_model("EXPLAINING")
        facts = {
            "plan": await self._current_plan(),
            "input": loaded["input_text"][:2000],
            "tool_results": [
                content_text(message.content)[:1000]
                for message in messages
                if getattr(message, "type", "") == "tool"
            ][-4:],
        }
        return await self.stream_response(prompts.COMPOSE + prompts.SCHEDULING_COMPOSE, facts)

    async def explain_workbench(self):
        facts = await self._current_plan()
        fallback = (
            f"已安排 {facts.get('assigned_order_count', 0)} 笔订单，"
            f"还有 {facts.get('unassigned_count', 0)} 笔未安排。请核对机器和顺序后确认排单。"
        )
        try:
            await self.count_model("EXPLAINING")
            model = await self._model()
            reply = await model.ainvoke(
                self.bounded_messages(
                    "你是排单说明助手。依据下面已生成的草稿，用不超过三句话说明合单、机器选择和未安排原因。"
                    "只复述提供的事实；不要虚构交期、效率或已下发。米数订单可按规格合并，不与重量混合，不估算kg。"
                    "TASK_COUNT仅为同等条件下任务数粗略比较，不是工时。不提工具和技术实现。最多150字。"
                    + json.dumps(facts, ensure_ascii=False),
                    [],
                )
            )
            await self.usage(reply)
            return content_text(reply.content)[:400] or fallback
        except LeaseLost:
            raise
        except Exception:
            # A valid persisted draft remains usable if the optional explanation fails.
            return fallback

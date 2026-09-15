"""Shared bounded text-model I/O; specialized capabilities own business permissions."""

import asyncio
import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.agent.limits import MAX_CONTEXT_TEXT_BYTES, MAX_MODEL_CALLS
from app.agent.model_transport import content_text
from app.agent.specialized import prompts
from app.agent.specialized.admission import Admission, parse_admission
from app.agent.worker import append_delta, lock_run
from app.core.config import settings
from app.core.database import async_session
from app.services.agent_event_service import append_event


class ModelIO:
    def __init__(self, context, *, sessions=async_session, model=None):
        self.context, self.sessions, self.model = context, sessions, model
        self.loaded, self.bound_model = None, None

    async def _model(self):
        if self.model is None:
            async with self.sessions() as db:
                _, run = await lock_run(db, self.context)
                model_id = run.config_snapshot["model_id"]
            if not settings.LLM_API_KEY:
                raise RuntimeError("model unavailable")
            self.model = ChatOpenAI(
                model=model_id,
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL,
                temperature=0,
                timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
                max_retries=0,
                max_tokens=4096,
            )
        return self.model

    async def admit_input(self, payload: dict) -> Admission:
        await self.count_model("ADMITTANCE")
        model = await self._model()
        reply = await model.ainvoke(
            [
                SystemMessage(
                    content=(
                        prompts.ADMITTANCE
                        + "\n输出Schema："
                        + json.dumps(Admission.model_json_schema(), ensure_ascii=False)
                    )
                ),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
            ],
            response_format={"type": "json_object"},
        )
        await self.usage(reply)
        return parse_admission(reply)

    async def count_model(self, stage: str) -> None:
        async with self.sessions() as db:
            session, run = await lock_run(db, self.context)
            if run.model_call_count >= MAX_MODEL_CALLS:
                raise RuntimeError("model call limit")
            run.model_call_count += 1
            append_event(db, session, "run.progress", {"stage": stage}, run_id=run.id)
            await db.commit()

    async def usage(self, message) -> None:
        usage = getattr(message, "usage_metadata", None)
        async with self.sessions() as db:
            _, run = await lock_run(db, self.context)
            context = dict(run.context_snapshot or {})
            if not usage:
                context["usage_complete"] = False
            else:
                for column, source in (
                    ("prompt_tokens", "input_tokens"),
                    ("completion_tokens", "output_tokens"),
                    ("total_tokens", "total_tokens"),
                ):
                    if source not in usage:
                        context["usage_complete"] = False
                    else:
                        setattr(run, column, (getattr(run, column) or 0) + usage[source])
            run.context_snapshot = context
            await db.commit()

    @staticmethod
    def bounded_messages(system: str, messages: list) -> list:
        # UTF-8 bytes are a conservative upper bound for text tokenization.
        # Reserve space for tool schemas and 4k output tokens; keep whole tool exchanges.
        remaining = MAX_CONTEXT_TEXT_BYTES - len(system.encode())
        if remaining < 0:
            raise RuntimeError("context limit")
        groups = []
        for message in messages:
            if getattr(message, "type", "") == "tool" and groups:
                groups[-1].append(message)
            else:
                groups.append([message])
        selected = []
        for group in reversed(groups):
            size = len(json.dumps([m.model_dump() for m in group], ensure_ascii=False, default=str).encode())
            if size > remaining:
                break
            selected[0:0] = group
            remaining -= size
        if messages and not selected:
            raise RuntimeError("context limit")
        return [SystemMessage(content=system), *selected]

    async def stream_response(self, system: str, facts: dict) -> str:
        from langchain_core.messages import HumanMessage

        model = await self._model()
        inputs = self.bounded_messages(system, [HumanMessage(content=json.dumps(facts, ensure_ascii=False))])
        if len(inputs) != 2:
            raise RuntimeError("context limit")
        text, buffer, chunk_index = "", "", 0
        last_flush = asyncio.get_running_loop().time()
        usage_seen = False
        async for chunk in model.astream(inputs):
            content = content_text(chunk.content)
            if len(text) + len(content) > 20000:
                raise RuntimeError("response limit")
            text += content
            buffer += content
            if len(buffer) >= 256 or asyncio.get_running_loop().time() - last_flush >= 0.1:
                for offset in range(0, len(buffer), 4096):
                    async with self.sessions() as db:
                        await append_delta(db, self.context, buffer[offset : offset + 4096], chunk_index)
                    chunk_index += 1
                buffer, last_flush = "", asyncio.get_running_loop().time()
            if getattr(chunk, "usage_metadata", None):
                usage_seen = True
                await self.usage(chunk)
        if buffer:
            async with self.sessions() as db:
                await append_delta(db, self.context, buffer, chunk_index)
        if not usage_seen:
            await self.usage(None)
        return text

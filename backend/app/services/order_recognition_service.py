"""Apply one screenshot atomically inside the fenced tool transaction; never commit here."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatSession, OrderIntakeItem
from app.models.base import generate_id
from app.schemas.agent.order_extraction import OrderExtraction, ScreenshotExtraction
from app.schemas.agent.order_intake import OrderDraft
from app.services import agent_session_service as sessions
from app.services.agent_event_service import append_event
from app.services.agent_projections import item_snapshot
from app.services.order_draft_service import validate_draft
from app.services.order_extraction_normalizer import normalize_extraction
from app.services.order_intake_item_service import patch_draft, require_item_revision
from app.services.order_matching_service import suggested_draft


async def save_extraction(
    db: AsyncSession,
    session: ChatSession,
    item: OrderIntakeItem,
    raw: OrderExtraction,
    expected: int,
    run_id: str,
    suggestions: dict | None = None,
) -> dict:
    require_item_revision(item, expected)
    proposed, match_issues = await suggested_draft(db, raw, suggestions or {})
    # Recognition retries preserve every user-supplied field, including intentionally cleared values.
    patch = {}
    for field, value in proposed.items():
        if field == "schema_version":
            continue
        if field == "spec_params":
            patch[field] = {
                key: val
                for key, val in value.items()
                if item.provenance.get(f"spec_params.{key}", {}).get("source") != "USER"
            }
        elif item.provenance.get(field, {}).get("source") != "USER":
            patch[field] = value
    # An independently protected formula field must not yield an inconsistent mode/ID pair.
    if any(
        item.provenance.get(field, {}).get("source") == "USER" for field in ("formula_id", "formula_mode")
    ):
        patch.pop("formula_id", None)
        patch.pop("formula_mode", None)
    item.extraction = raw.model_dump()
    item.recognition_status, item.last_error_code = "SUCCEEDED", None
    await patch_draft(db, session, item, expected, patch, source="EXTRACTION", run_id=run_id)
    _, inference_issues = normalize_extraction(raw)
    item.issues += [
        issue
        for issue in inference_issues + match_issues
        if item.provenance.get(issue["field"], {}).get("source") != "USER"
    ]
    if raw.warnings:
        item.issues = item.issues + [
            {
                "field": "source",
                "code": "RECOGNITION_WARNING",
                "severity": "warning",
                "message": warning,
                "candidates": [],
            }
            for warning in raw.warnings
        ]
    append_event(
        db, session, "recognition.completed", {"revision": item.revision}, run_id=run_id, work_item_id=item.id
    )
    return item_snapshot(item)


async def save_screenshot_extraction(
    db: AsyncSession,
    session: ChatSession,
    item: OrderIntakeItem,
    raw: ScreenshotExtraction,
    expected: int,
    run_id: str,
    suggestions: dict | None = None,
) -> dict:
    """Save the entire screenshot in the fenced tool transaction, or save nothing."""
    require_item_revision(item, expected)
    if item.source_order_index != 1 or item.recognition_status == "SUCCEEDED":
        sessions.fail("ACTION_STALE", "此截图已识别，请使用已保存的订单草稿")
    existing = await db.scalar(
        select(OrderIntakeItem.id)
        .where(
            OrderIntakeItem.source_attachment_id == item.source_attachment_id,
            OrderIntakeItem.source_order_index > 1,
        )
        .limit(1)
    )
    if existing:
        sessions.fail("ACTION_STALE", "此截图已有订单草稿")
    suggestions = suggestions or {}
    result = await save_extraction(db, session, item, raw.orders[0], expected, run_id, suggestions.get(1))
    for index, evidence in enumerate(raw.orders[1:], start=2):
        proposed, match_issues = await suggested_draft(db, evidence, suggestions.get(index, {}))
        draft = OrderDraft.model_validate(proposed)
        _, inference_issues = normalize_extraction(evidence)
        issues = await validate_draft(db, draft) + inference_issues + match_issues
        issues += [
            dict(
                field="source", code="RECOGNITION_WARNING", severity="warning", message=warning, candidates=[]
            )
            for warning in evidence.warnings
        ]
        sibling = OrderIntakeItem(
            id=generate_id(),
            session_id=session.id,
            source_message_id=item.source_message_id,
            source_attachment_id=item.source_attachment_id,
            queue_position=item.queue_position,
            source_order_index=index,
            status="PENDING",
            recognition_status="SUCCEEDED",
            extraction=evidence.model_dump(),
            draft=draft.model_dump(),
            issues=issues,
            provenance={
                field: dict(
                    source="EXTRACTION",
                    source_message_id=item.source_message_id,
                    source_attachment_id=item.source_attachment_id,
                    source_run_id=run_id,
                )
                for field in OrderDraft.model_fields
            },
        )
        db.add(sibling)
        append_event(
            db,
            session,
            "work_item.queued",
            {"position": item.queue_position, "source_order_index": index},
            run_id=run_id,
            work_item_id=sibling.id,
        )
        append_event(
            db, session, "recognition.completed", {"revision": 1}, run_id=run_id, work_item_id=sibling.id
        )
    session.state_revision += 1
    append_event(
        db, session, "session.state_changed", {"state_revision": session.state_revision}, run_id=run_id
    )
    return {**result, "recognized_order_count": len(raw.orders)}

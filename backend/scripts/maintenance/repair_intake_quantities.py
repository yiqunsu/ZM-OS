"""Explicitly scoped, transactional repair of blank quantities from retained extraction.

Defaults to dry-run. --apply requires a new private backup file before commit.
"""

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.models import OrderIntakeItem
from app.schemas.agent.order_intake import OrderDraft
from app.services import agent_session_service as sessions
from app.services.agent_event_service import append_event
from app.services.order_intake_item_service import validate_draft
from scripts.maintenance.extraction import extracted_quantity


async def repair(db: AsyncSession, item_ids: list[str]) -> list[dict]:
    items = (await db.scalars(select(OrderIntakeItem).where(OrderIntakeItem.id.in_(item_ids)))).all()
    if len(items) != len(set(item_ids)):
        raise ValueError("requested item missing")
    changes = []
    for sid in sorted({item.session_id for item in items}):
        # Session lock serializes repair with every API/Worker write and freezes selection.
        from app.models import ChatSession

        owner = await db.get(ChatSession, sid)
        session = await sessions.require_session(db, sid, owner.user_id, lock=True, writable=True)
        await sessions.require_idle(db, session)
        rows = (
            await db.scalars(
                select(OrderIntakeItem)
                .where(OrderIntakeItem.id.in_(item_ids), OrderIntakeItem.session_id == sid)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
        for item in rows:
            before = dict(item.draft)
            if (
                item.status not in {"ACTIVE", "DEFERRED", "PENDING"}
                or item.order_id
                or item.recognition_status != "SUCCEEDED"
                or before.get("quantity") is not None
                or any(
                    item.provenance.get(field, {}).get("source") == "USER" for field in ("quantity", "unit")
                )
            ):
                continue
            raw = item.extraction or {}
            quantity, unit, note = extracted_quantity(raw.get("quantity_raw"), raw.get("unit_raw"))
            if quantity is None or unit is None or before.get("unit") not in {None, unit}:
                continue
            after = {**before, "quantity": quantity, "unit": unit}
            fields = ["quantity", "unit"]
            if (
                note
                and note not in (before.get("extra_notes") or "")
                and item.provenance.get("extra_notes", {}).get("source") != "USER"
            ):
                after["extra_notes"] = "；".join(filter(None, [note, before.get("extra_notes")]))[:2000]
                fields.append("extra_notes")
            draft = OrderDraft.model_validate(after)
            changes.append(
                {
                    "item_id": item.id,
                    "before": {
                        "draft": before,
                        "revision": item.revision,
                        "issues": item.issues,
                        "provenance": item.provenance,
                        "updated_at": item.updated_at.isoformat(),
                    },
                    "quantity": quantity,
                    "unit": unit,
                }
            )
            retained = [i for i in item.issues if i["code"] in {"UNIT_INFERRED", "RECOGNITION_WARNING"}]
            item.draft = draft.model_dump()
            item.issues = await validate_draft(db, draft) + retained
            provenance = dict(item.provenance)
            for field in fields:
                provenance[field] = {
                    "source": "EXTRACTION",
                    "source_message_id": item.source_message_id,
                    "source_attachment_id": item.source_attachment_id,
                    "source_run_id": None,
                }
            item.provenance = provenance
            item.revision += 1
            item.updated_at = datetime.now(UTC)
            append_event(
                db,
                session,
                "draft.updated",
                {"revision": item.revision, "repair": "quantity_text"},
                work_item_id=item.id,
            )
    return changes


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--item-id", action="append", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup")
    args = parser.parse_args()
    if args.apply and not args.backup:
        parser.error("--apply requires --backup")
    async with async_session() as db:
        async with db.begin():
            changes = await repair(db, args.item_id)
            if args.apply:
                path = Path(args.backup)
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "w") as output:
                    json.dump(changes, output, ensure_ascii=False)
                    output.flush()
                    os.fsync(output.fileno())
            else:
                await db.rollback()
        print(
            json.dumps(
                {
                    "applied": args.apply,
                    "changes": [{k: v for k, v in c.items() if k != "before"} for c in changes],
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())

"""Screenshot display numbering is independent of durable queue IDs and item pages."""
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import ChatAttachment, OrderIntakeItem
from tests.test_agent_v2 import body, create, enable_v2, upload  # noqa: F401


async def test_upload_day_ranks_partial_close_pagination_and_queue_stability(client, db_session):
    sid = (await create(client, "ORDER_INTAKE"))["id"]
    images = [await upload(client, sid) for _ in range(4)]
    # An unsubmitted staged upload must not consume a visible screenshot number.
    await upload(client, sid)
    response = await client.post(
        f"/api/agent/v2/sessions/{sid}/recognize",
        json=body(content="", attachment_ids=[image["id"] for image in images]),
    )
    assert response.status_code == 202
    rows = list((await db_session.scalars(
        select(OrderIntakeItem)
        .where(OrderIntakeItem.session_id == sid)
        .order_by(OrderIntakeItem.queue_position)
    )).all())
    # Beijing midnight splits the first two; the third/fourth upload order differs from queue order.
    for image, hour, minute in zip(images, [15, 16, 17, 16], [59, 0, 0, 30], strict=True):
        attachment = await db_session.get(ChatAttachment, image["id"])
        attachment.created_at = datetime(2026, 9, 12, hour, minute, tzinfo=timezone.utc)
    sibling = OrderIntakeItem(
        session_id=sid, source_message_id=rows[1].source_message_id,
        source_attachment_id=rows[1].source_attachment_id, queue_position=rows[1].queue_position,
        source_order_index=2, draft=rows[1].draft,
        # Recognition on a different day must not change upload grouping.
        created_at=datetime(2026, 9, 15, tzinfo=timezone.utc),
    )
    db_session.add(sibling)
    await db_session.commit()
    async def snapshot():
        return (await client.get(f"/api/agent/v2/sessions/{sid}/snapshot")).json()["work_items"]
    initial = {i["id"]: i for i in await snapshot()}
    assert [initial[i.id]["source_day_position"] for i in rows] == [1, 1, 3, 2]
    assert initial[rows[0].id]["source_day"] == "2026-09-12"
    assert initial[sibling.id]["source_day"] == "2026-09-13"
    assert initial[sibling.id]["source_day_position"] == 1
    # A later page/standalone detail ranks against the whole day, not just that page.
    page = (await client.get(f"/api/agent/v2/sessions/{sid}/items?cursor=2:2&limit=1")).json()
    assert page["items"][0]["source_day_position"] == 3
    assert page["next_cursor"] == "3:1"
    rows[1].status = "CLOSED"
    await db_session.commit()
    partial = {i["id"]: i for i in await snapshot()}
    assert partial[rows[2].id]["source_day_position"] == 3
    sibling.status = "CLOSED"
    await db_session.commit()
    closed = {i["id"]: i for i in await snapshot()}
    assert closed[rows[2].id]["source_day_position"] == 2
    assert closed[rows[3].id]["source_day_position"] == 1
    assert "source_day_position" not in closed[sibling.id]
    detail = (await client.get(f"/api/agent/v2/items/{rows[2].id}")).json()
    assert detail["source_day_position"] == 2
    assert detail["queue_position"] == 3
    assert [i.queue_position for i in rows] == [1, 2, 3, 4]
    # No closed screenshot consumes a display number.
    for row in rows:
        row.status = "CLOSED"
    await db_session.commit()
    assert all("source_day_position" not in i for i in await snapshot())

"""One user-wide collection; screenshot archives preserve drafts and isolate all write paths."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select

from app.agent.worker import claim, fail_run
from app.models import ChatAttachment, ChatSession, Order, OrderIntakeItem, User
from app.services.order_intake_workflow import advance_review
from tests.test_agent_v2 import body, create, enable_v2, upload  # noqa: F401
from tests.test_order_intake_v2 import setup_item


async def prepared(client, db):
    sid, iid = await setup_item(client, db)
    context = await claim(db, "library-test")
    await fail_run(db, context, "TEST", "test")
    item = await db.get(OrderIntakeItem, iid)
    item.recognition_status = "SUCCEEDED"
    item.draft = {**item.draft, "quantity": "7500", "unit": "m", "extra_notes": "保留原文"}
    image = await db.get(ChatAttachment, item.source_attachment_id)
    image.created_at = datetime(2026, 9, 13, 1, tzinfo=UTC)
    await db.commit()
    return sid, item, image


async def command(client, image, action="archive", revision=0, key=None):
    return await client.post(
        f"/api/agent/v2/intake/screenshots/{image.id}/{action}",
        json={"expected_revision": revision},
        headers={"Idempotency-Key": key or str(uuid4())},
    )


async def listing(client, query=""):
    response = await client.get("/api/agent/v2/intake/screenshots" + query)
    assert response.status_code == 200, response.text
    return response.json()


async def test_global_date_rank_whole_screenshot_pages_and_owner_isolation(client, db_session):
    sid, first, image = await prepared(client, db_session)
    sid2, second, image2 = await prepared(client, db_session)
    image2.created_at = datetime(2026, 9, 13, 2, tzinfo=UTC)
    sibling = OrderIntakeItem(
        session_id=sid,
        source_message_id=first.source_message_id,
        source_attachment_id=image.id,
        queue_position=1,
        source_order_index=2,
        draft=first.draft,
    )
    db_session.add(sibling)
    await db_session.commit()
    page = await listing(client, "?limit=1")
    assert len(page["screenshots"]) == 1 and len(page["screenshots"][0]["items"]) == 2
    assert page["counts"]["ACTIVE"] == 2
    next_page = await listing(client, f'?limit=1&cursor={page["next_cursor"]}')
    assert next_page["screenshots"][0]["id"] == image2.id
    assert next_page["screenshots"][0]["source_day_position"] == 2
    assert {i["session_id"] for g in (await listing(client))["screenshots"] for i in g["items"]} == {
        sid,
        sid2,
    }
    # Existing session endpoints and the global list agree on ranks.
    assert (await client.get(f"/api/agent/v2/items/{second.id}")).json()["source_day_position"] == 2
    session2 = await db_session.get(ChatSession, sid2)
    db_session.add(User(id="other-library-user", email="other-library@example.invalid", password_hash="test"))
    await db_session.flush()
    session2.user_id = "other-library-user"
    await db_session.commit()
    assert len((await listing(client))["screenshots"]) == 1
    assert (await command(client, image2)).status_code == 404
    assert (await client.get(f"/api/agent/v2/attachments/{image2.id}/content")).status_code == 404
    first.status = sibling.status = "CLOSED"
    await db_session.commit()
    assert (await listing(client))["screenshots"] == []


async def test_archive_all_sibling_drafts_readonly_restore_and_idempotency(client, db_session):
    sid, first, image = await prepared(client, db_session)
    second = OrderIntakeItem(
        session_id=sid,
        source_message_id=first.source_message_id,
        source_attachment_id=image.id,
        queue_position=1,
        source_order_index=2,
        draft=first.draft,
        recognition_status="SUCCEEDED",
    )
    db_session.add(second)
    await db_session.commit()
    before = dict(first.draft)
    key = str(uuid4())
    result = await command(client, image, key=key)
    assert result.status_code == 200, result.text
    assert (await command(client, image, key=key)).json() == result.json()
    assert (await command(client, image)).status_code == 409
    assert (await listing(client))["screenshots"] == []
    archive = await listing(client, "?tab=archived")
    assert archive["counts"]["ARCHIVED"] == 2
    assert len(archive["screenshots"][0]["items"]) == 2
    await db_session.refresh(first)
    assert first.draft == before and first.status == "DEFERRED"
    assert (await client.get(f"/api/agent/v2/attachments/{image.id}/content")).status_code == 200
    for action in ("select", "confirm", "recognize", "close"):
        payload = (
            {"expected_revision": first.revision, "expected_state_revision": 3}
            if action == "select"
            else {"expected_revision": first.revision}
        )
        if action == "close":
            payload["confirmed"] = True
        blocked = await client.post(
            f"/api/agent/v2/items/{first.id}/{action}",
            json=payload,
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["error"]["code"] == "SCREENSHOT_ARCHIVED"
    blocked = await client.patch(
        f"/api/agent/v2/items/{first.id}/draft",
        json={"expected_revision": first.revision, "patch": {"quantity": "9000"}},
    )
    assert blocked.status_code == 409
    session = await db_session.get(ChatSession, sid)
    await advance_review(db_session, session)
    assert session.active_work_item_id is None  # Archived pending sibling is not auto-selected.
    assert (await command(client, image, "restore", 1)).status_code == 200
    active = (await listing(client))["screenshots"][0]
    assert active["source_day_position"] == 1 and not active["source_archived"]
    detail = (await client.get(f"/api/agent/v2/items/{first.id}")).json()
    assert detail["draft"] == before
    state = (await client.get(f"/api/agent/v2/sessions/{sid}/snapshot")).json()["session"]
    selected = await client.post(
        f"/api/agent/v2/items/{first.id}/select",
        json={"expected_revision": first.revision, "expected_state_revision": state["state_revision"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert selected.status_code == 200, selected.text
    assert await db_session.scalar(select(func.count()).select_from(Order)) == 0


async def test_busy_archive_rejected_without_hiding_input(client, db_session):
    sid, iid = await setup_item(client, db_session)
    item = await db_session.get(OrderIntakeItem, iid)
    image = await db_session.get(ChatAttachment, item.source_attachment_id)
    rejected = await command(client, image)
    assert rejected.status_code == 409
    await db_session.refresh(image)
    assert image.intake_archived_at is None and image.intake_revision == 0
    assert (await listing(client))["screenshots"][0]["busy"] is True


async def test_restore_one_legacy_archived_screenshot_keeps_siblings_archived(client, db_session):
    sid, item, image = await prepared(client, db_session)
    second_image = await upload(client, sid)
    # Bind through the real upload protocol, then terminate only the test run.
    state = (await client.get(f"/api/agent/v2/sessions/{sid}/snapshot")).json()["session"]
    response = await client.post(
        f"/api/agent/v2/sessions/{sid}/recognize",
        json=body(revision=state["state_revision"], content="", attachment_ids=[second_image["id"]]),
    )
    assert response.status_code == 202
    await fail_run(db_session, await claim(db_session, "legacy-test"), "TEST", "test")
    archived = await client.post(
        f"/api/agent/v2/sessions/{sid}/archive", json={}, headers={"Idempotency-Key": str(uuid4())}
    )
    assert archived.status_code == 200
    assert len((await listing(client, "?tab=archived"))["screenshots"]) == 2
    restored = await command(client, image, "restore")
    assert restored.status_code == 200, restored.text
    assert [g["id"] for g in (await listing(client))["screenshots"]] == [image.id]
    assert [g["id"] for g in (await listing(client, "?tab=archived"))["screenshots"]] == [second_image["id"]]
    await db_session.refresh(item)
    assert item.draft["quantity"] == "7500"


async def test_entry_reuses_workspace_and_invalid_input_is_rejected(client, db_session):
    results = []
    for _ in range(2):
        response = await client.post(
            "/api/agent/v2/intake/workspace", json={}, headers={"Idempotency-Key": str(uuid4())}
        )
        assert response.status_code == 200, response.text
        results.append(response.json()["session"]["id"])
    assert results[0] == results[1]
    assert await db_session.scalar(select(func.count()).select_from(ChatSession)) == 1
    assert (await client.get("/api/agent/v2/intake/screenshots?cursor=invalid")).status_code == 422
    assert (await client.get("/api/agent/v2/intake/screenshots?limit=0")).status_code == 422


async def test_archive_failure_rolls_back_visibility_and_active_draft(client, db_session, monkeypatch):
    import pytest

    from app.services import order_screenshot_service

    sid, item, image = await prepared(client, db_session)
    before = dict(item.draft)

    def reject_event(*args, **kwargs):
        raise RuntimeError("test transaction failure")

    monkeypatch.setattr(order_screenshot_service, "append_event", reject_event)
    with pytest.raises(RuntimeError, match="test transaction failure"):
        await command(client, image)
    await db_session.rollback()
    await db_session.refresh(image)
    await db_session.refresh(item)
    session = await db_session.get(ChatSession, sid)
    assert image.intake_archived_at is None and image.intake_revision == 0
    assert item.status == "ACTIVE" and item.draft == before
    assert session.active_work_item_id == item.id
    assert len((await listing(client))["screenshots"]) == 1

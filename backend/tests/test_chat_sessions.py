from app.models import ChatMessage, ChatSession, User, UserRole


async def test_chat_sessions_are_scoped_to_authenticated_user(client, db_session):
    other_user = User(
        email="other@filmos.local",
        password_hash="test-only-not-a-real-password-hash",
        role=UserRole.OPERATOR,
    )
    db_session.add(other_user)
    await db_session.flush()

    other_session = ChatSession(title="other", user_id=other_user.id)
    legacy_session = ChatSession(title="legacy", user_id=None)
    db_session.add_all([other_session, legacy_session])
    await db_session.flush()
    db_session.add(ChatMessage(session_id=other_session.id, role="user", content="private"))
    await db_session.commit()

    create_response = await client.post("/api/agent/sessions")
    assert create_response.status_code == 200
    owned_session_id = create_response.json()["id"]

    list_response = await client.get("/api/agent/sessions")
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [owned_session_id]

    for hidden_session_id in (other_session.id, legacy_session.id):
        history_response = await client.get("/api/agent/chat", params={"session_id": hidden_session_id})
        assert history_response.status_code == 404

        send_response = await client.post(
            "/api/agent/chat",
            json={"content": "hello", "session_id": hidden_session_id},
        )
        assert send_response.status_code == 404

        delete_response = await client.delete(f"/api/agent/sessions/{hidden_session_id}")
        assert delete_response.status_code == 404


async def test_chat_history_is_available_to_session_owner(client):
    create_response = await client.post("/api/agent/sessions")
    session_id = create_response.json()["id"]

    history_response = await client.get("/api/agent/chat", params={"session_id": session_id})

    assert history_response.status_code == 200
    assert history_response.json() == []


async def test_order_workspace_draft_survives_reload_and_clears(client):
    create_response = await client.post("/api/agent/sessions")
    session_id = create_response.json()["id"]
    draft = {
        "customer_id": "customer-1",
        "product_id": "product-1",
        "spec_params": {"厚度": "50μm"},
        "quantity": "500",
        "unit": "kg",
        "formula_mode": "none",
        "formula_id": "",
        "formula_materials": "",
        "new_formula_name": "",
        "new_formula_materials": "",
        "extra_notes": "测试草稿",
    }

    save_response = await client.put(
        "/api/agent/workspace/order-draft",
        json={"session_id": session_id, "draft": draft},
    )
    assert save_response.status_code == 200

    workspace_response = await client.get(
        "/api/agent/workspace",
        params={"session_id": session_id},
    )
    assert workspace_response.status_code == 200
    assert workspace_response.json() == {
        "active_workspace": "order_form",
        "order_draft": draft,
        "schedule_plan": None,
    }

    close_response = await client.post(
        "/api/agent/workspace/close",
        json={"session_id": session_id},
    )
    assert close_response.status_code == 204
    cleared_response = await client.get(
        "/api/agent/workspace",
        params={"session_id": session_id},
    )
    assert cleared_response.json() == {
        "active_workspace": None,
        "order_draft": None,
        "schedule_plan": None,
    }

async def _setup(client):
    cat = (await client.post("/api/product-categories", json={"name": "PE膜"})).json()
    prod = (await client.post("/api/products", json={"name": "透明膜", "category_id": cat["id"]})).json()
    cust = (await client.post("/api/customers", json={"company": "华兴包装", "contact": "张三"})).json()
    return cat, prod, cust


async def test_kanban_excludes_inactive_machines(client):
    _, _, _ = await _setup(client)
    active = (await client.post("/api/machines", json={
        "name": "1号机", "min_width": 100, "max_width": 1200,
    })).json()
    await client.post("/api/machines", json={
        "name": "2号机（停用）", "min_width": 100, "max_width": 1200, "is_active": False,
    })

    kanban = (await client.get("/api/kanban")).json()
    machine_ids = [m["id"] for m in kanban["machines"]]
    assert active["id"] in machine_ids
    assert len(kanban["machines"]) == 1


async def test_kanban_lists_unassigned_pending_orders(client):
    _cat, prod, cust = await _setup(client)
    order = (await client.post("/api/orders", json={
        "customer_id": cust["id"], "product_id": prod["id"], "spec_params": {}, "quantity": 100, "unit": "kg",
    })).json()

    kanban = (await client.get("/api/kanban")).json()
    pending_ids = [o["id"] for o in kanban["pending_orders"]]
    assert order["id"] in pending_ids


async def test_kanban_hides_done_tasks_but_keeps_producing(client):
    _cat, prod, cust = await _setup(client)
    machine = (await client.post("/api/machines", json={
        "name": "1号机", "min_width": 100, "max_width": 1200,
    })).json()
    order1 = (await client.post("/api/orders", json={
        "customer_id": cust["id"], "product_id": prod["id"], "spec_params": {}, "quantity": 100, "unit": "kg",
    })).json()
    order2 = (await client.post("/api/orders", json={
        "customer_id": cust["id"], "product_id": prod["id"], "spec_params": {}, "quantity": 50, "unit": "kg",
    })).json()
    task_done = (await client.post("/api/production-tasks", json={
        "machine_id": machine["id"], "order_ids": [order1["id"]],
    })).json()
    task_active = (await client.post("/api/production-tasks", json={
        "machine_id": machine["id"], "order_ids": [order2["id"]],
    })).json()
    await client.put(f"/api/production-tasks/{task_done['id']}", json={"status": "DONE"})

    kanban = (await client.get("/api/kanban")).json()
    task_ids = [t["id"] for m in kanban["machines"] for t in m["tasks"]]
    assert task_active["id"] in task_ids
    assert task_done["id"] not in task_ids

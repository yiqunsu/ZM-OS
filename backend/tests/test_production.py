async def _setup(client, n_orders=1):
    cat = (await client.post("/api/product-categories", json={"name": "PE膜"})).json()
    prod = (await client.post("/api/products", json={"name": "透明膜", "category_id": cat["id"]})).json()
    cust = (await client.post("/api/customers", json={"company": "华兴包装", "contact": "张三"})).json()
    machine = (await client.post("/api/machines", json={
        "name": "1号机", "min_width": 100, "max_width": 1200,
    })).json()
    orders = []
    for _ in range(n_orders):
        orders.append((await client.post("/api/orders", json={
            "customer_id": cust["id"], "product_id": prod["id"],
            "spec_params": {}, "quantity": 100, "unit": "kg",
        })).json())
    return machine, orders


async def test_create_task_sets_orders_producing(client):
    machine, orders = await _setup(client, 1)
    res = await client.post("/api/production-tasks", json={
        "machine_id": machine["id"], "order_ids": [orders[0]["id"]],
    })
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "PRODUCING"
    assert body["orders"][0]["status"] == "PRODUCING"


async def test_task_position_increments_per_machine(client):
    machine, orders = await _setup(client, 2)
    task1 = (await client.post("/api/production-tasks", json={
        "machine_id": machine["id"], "order_ids": [orders[0]["id"]],
    })).json()
    task2 = (await client.post("/api/production-tasks", json={
        "machine_id": machine["id"], "order_ids": [orders[1]["id"]],
    })).json()
    assert task2["position"] == task1["position"] + 1


async def test_merge_order_into_task_via_order_ids_update(client):
    machine, orders = await _setup(client, 2)
    task = (await client.post("/api/production-tasks", json={
        "machine_id": machine["id"], "order_ids": [orders[0]["id"]],
    })).json()

    res = await client.put(f"/api/production-tasks/{task['id']}", json={
        "order_ids": [orders[0]["id"], orders[1]["id"]],
    })
    body = res.json()
    assert len(body["orders"]) == 2
    reloaded = (await client.get(f"/api/orders/{orders[1]['id']}")).json()
    assert reloaded["status"] == "PRODUCING"
    assert reloaded["task_id"] == task["id"]


async def test_removing_order_from_task_returns_it_to_pending(client):
    machine, orders = await _setup(client, 2)
    task = (await client.post("/api/production-tasks", json={
        "machine_id": machine["id"], "order_ids": [orders[0]["id"], orders[1]["id"]],
    })).json()

    await client.put(f"/api/production-tasks/{task['id']}", json={"order_ids": [orders[0]["id"]]})

    reloaded = (await client.get(f"/api/orders/{orders[1]['id']}")).json()
    assert reloaded["status"] == "PENDING"
    assert reloaded["task_id"] is None


async def test_marking_task_done_cascades_to_orders(client):
    machine, orders = await _setup(client, 1)
    task = (await client.post("/api/production-tasks", json={
        "machine_id": machine["id"], "order_ids": [orders[0]["id"]],
    })).json()

    await client.put(f"/api/production-tasks/{task['id']}", json={"status": "DONE"})

    reloaded = (await client.get(f"/api/orders/{orders[0]['id']}")).json()
    assert reloaded["status"] == "DONE"


async def test_delete_task_returns_all_orders_to_pending(client):
    machine, orders = await _setup(client, 2)
    task = (await client.post("/api/production-tasks", json={
        "machine_id": machine["id"], "order_ids": [orders[0]["id"], orders[1]["id"]],
    })).json()

    res = await client.delete(f"/api/production-tasks/{task['id']}")
    assert res.status_code == 204

    for o in orders:
        reloaded = (await client.get(f"/api/orders/{o['id']}")).json()
        assert reloaded["status"] == "PENDING"
        assert reloaded["task_id"] is None

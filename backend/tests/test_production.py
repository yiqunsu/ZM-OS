async def _setup(client, n_orders=1, *, machine_name="1号机"):
    category = (await client.post("/api/product-categories", json={"name": "PE膜"})).json()
    product = (
        await client.post(
            "/api/products",
            json={"name": "透明膜", "category_id": category["id"]},
        )
    ).json()
    customer = (
        await client.post(
            "/api/customers",
            json={"company": "华兴包装", "contact": "张三"},
        )
    ).json()
    formula = (
        await client.post(
            "/api/formulas",
            json={
                "name": "标准配方",
                "product_id": product["id"],
                "materials": "PE-A",
            },
        )
    ).json()
    machine = (
        await client.post(
            "/api/machines",
            json={
                "name": machine_name,
                "min_width": 100,
                "max_width": 1200,
                "category_ids": [category["id"]],
            },
        )
    ).json()
    orders = []
    for _ in range(n_orders):
        orders.append(
            (
                await client.post(
                    "/api/orders",
                    json={
                        "customer_id": customer["id"],
                        "product_id": product["id"],
                        "formula_id": formula["id"],
                        "spec_params": {"宽度": "400mm", "厚度": "50μm"},
                        "quantity": 100,
                        "unit": "kg",
                    },
                )
            ).json()
        )
    return machine, orders


async def _create_task(client, machine_id, order_ids):
    response = await client.post(
        "/api/production-tasks",
        json={"machine_id": machine_id, "order_ids": order_ids},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_task_is_waiting_and_sets_orders_producing(client):
    machine, orders = await _setup(client, 1)

    task = await _create_task(client, machine["id"], [orders[0]["id"]])

    assert task["status"] == "WAITING"
    assert task["orders"][0]["status"] == "PRODUCING"


async def test_task_position_increments_per_machine(client):
    machine, orders = await _setup(client, 2)
    task1 = await _create_task(client, machine["id"], [orders[0]["id"]])
    task2 = await _create_task(client, machine["id"], [orders[1]["id"]])

    assert task2["position"] == task1["position"] + 1


async def test_move_order_merges_atomically_and_generic_update_is_blocked(client):
    machine, orders = await _setup(client, 2)
    task = await _create_task(client, machine["id"], [orders[0]["id"]])

    legacy = await client.put(
        f"/api/production-tasks/{task['id']}",
        json={"order_ids": [orders[0]["id"], orders[1]["id"]]},
    )
    assert legacy.status_code == 400

    response = await client.post(
        "/api/production-tasks/actions/move-order",
        json={"order_id": orders[1]["id"], "target_task_id": task["id"]},
    )

    assert response.status_code == 200, response.text
    merged = response.json()["machines"][0]["tasks"][0]
    assert {order["id"] for order in merged["orders"]} == {order["id"] for order in orders}
    reloaded = (await client.get(f"/api/orders/{orders[1]['id']}")).json()
    assert reloaded["status"] == "PRODUCING"
    assert reloaded["task_id"] == task["id"]


async def test_move_order_to_pending_deletes_empty_source_task(client):
    machine, orders = await _setup(client, 1)
    task = await _create_task(client, machine["id"], [orders[0]["id"]])

    response = await client.post(
        "/api/production-tasks/actions/move-order",
        json={"order_id": orders[0]["id"], "source_task_id": task["id"]},
    )

    assert response.status_code == 200, response.text
    board = response.json()
    assert board["machines"][0]["tasks"] == []
    assert [order["id"] for order in board["pending_orders"]] == [orders[0]["id"]]


async def test_task_status_follows_waiting_producing_done_and_only_one_can_run(client):
    machine, orders = await _setup(client, 2)
    first = await _create_task(client, machine["id"], [orders[0]["id"]])
    second = await _create_task(client, machine["id"], [orders[1]["id"]])

    invalid = await client.put(
        f"/api/production-tasks/{first['id']}", json={"status": "DONE"}
    )
    assert invalid.status_code == 409

    started = await client.put(
        f"/api/production-tasks/{first['id']}", json={"status": "PRODUCING"}
    )
    assert started.status_code == 200
    occupied = await client.put(
        f"/api/production-tasks/{second['id']}", json={"status": "PRODUCING"}
    )
    assert occupied.status_code == 409

    done = await client.put(
        f"/api/production-tasks/{first['id']}", json={"status": "DONE"}
    )
    assert done.status_code == 200
    reloaded = (await client.get(f"/api/orders/{orders[0]['id']}")).json()
    assert reloaded["status"] == "DONE"


async def test_delete_waiting_task_returns_all_orders_to_pending(client):
    machine, orders = await _setup(client, 2)
    task = await _create_task(client, machine["id"], [order["id"] for order in orders])

    response = await client.delete(f"/api/production-tasks/{task['id']}")

    assert response.status_code == 204
    for order in orders:
        reloaded = (await client.get(f"/api/orders/{order['id']}")).json()
        assert reloaded["status"] == "PENDING"
        assert reloaded["task_id"] is None


async def test_incompatible_machine_rejection_keeps_order_pending(client):
    _machine, orders = await _setup(client, 1)
    incompatible = (
        await client.post(
            "/api/machines",
            json={"name": "不兼容机器", "min_width": 100, "max_width": 1200},
        )
    ).json()

    response = await client.post(
        "/api/production-tasks",
        json={"machine_id": incompatible["id"], "order_ids": [orders[0]["id"]]},
    )

    assert response.status_code == 409
    reloaded = (await client.get(f"/api/orders/{orders[0]['id']}")).json()
    assert reloaded["status"] == "PENDING"
    assert reloaded["task_id"] is None


async def test_reorder_requires_the_complete_current_queue(client):
    machine, orders = await _setup(client, 2)
    first = await _create_task(client, machine["id"], [orders[0]["id"]])
    second = await _create_task(client, machine["id"], [orders[1]["id"]])

    stale = await client.post(
        "/api/production-tasks/actions/reorder",
        json={"machine_id": machine["id"], "ordered_task_ids": [first["id"]]},
    )
    assert stale.status_code == 409

    response = await client.post(
        "/api/production-tasks/actions/reorder",
        json={
            "machine_id": machine["id"],
            "ordered_task_ids": [second["id"], first["id"]],
        },
    )
    assert response.status_code == 200, response.text
    tasks = response.json()["machines"][0]["tasks"]
    assert [task["id"] for task in tasks] == [second["id"], first["id"]]
    assert [task["position"] for task in tasks] == [1, 2]

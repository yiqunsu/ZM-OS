async def test_create_machine_rejects_invalid_width_range(client):
    res = await client.post("/api/machines", json={
        "name": "1号机", "min_width": 1200, "max_width": 100,
    })
    assert res.status_code == 400


async def test_create_machine_with_categories(client):
    cat = (await client.post("/api/product-categories", json={"name": "PE膜"})).json()
    res = await client.post("/api/machines", json={
        "name": "1号机", "min_width": 100, "max_width": 1200, "category_ids": [cat["id"]],
    })
    assert res.status_code == 201
    body = res.json()
    assert body["categories"][0]["id"] == cat["id"]


async def test_update_machine_replaces_category_associations(client):
    cat1 = (await client.post("/api/product-categories", json={"name": "PE膜"})).json()
    cat2 = (await client.post("/api/product-categories", json={"name": "PVC膜"})).json()
    machine = (await client.post("/api/machines", json={
        "name": "1号机", "min_width": 100, "max_width": 1200, "category_ids": [cat1["id"]],
    })).json()

    res = await client.put(f"/api/machines/{machine['id']}", json={
        "name": "1号机", "min_width": 100, "max_width": 1200, "category_ids": [cat2["id"]],
    })
    ids = [c["id"] for c in res.json()["categories"]]
    assert ids == [cat2["id"]]


async def test_delete_machine_blocked_when_tasks_exist(client):
    cat = (await client.post("/api/product-categories", json={"name": "PE膜"})).json()
    prod = (await client.post("/api/products", json={"name": "透明膜", "category_id": cat["id"]})).json()
    cust = (await client.post("/api/customers", json={"company": "华兴包装", "contact": "张三"})).json()
    machine = (await client.post("/api/machines", json={
        "name": "1号机", "min_width": 100, "max_width": 1200,
    })).json()
    order = (await client.post("/api/orders", json={
        "customer_id": cust["id"], "product_id": prod["id"], "spec_params": {}, "quantity": 100, "unit": "kg",
    })).json()
    await client.post("/api/production-tasks", json={"machine_id": machine["id"], "order_ids": [order["id"]]})

    res = await client.delete(f"/api/machines/{machine['id']}")
    assert res.status_code == 409

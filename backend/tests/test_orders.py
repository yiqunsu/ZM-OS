async def _make_product(client):
    cat = (await client.post("/api/product-categories", json={"name": "PE膜"})).json()
    return (await client.post("/api/products", json={"name": "透明膜", "category_id": cat["id"]})).json()


async def _make_customer(client):
    return (await client.post("/api/customers", json={"company": "华兴包装", "contact": "张三"})).json()


async def test_create_order_generates_order_no_and_increments(client):
    prod = await _make_product(client)
    cust = await _make_customer(client)

    order1 = (
        await client.post(
            "/api/orders",
            json={
                "customer_id": cust["id"],
                "product_id": prod["id"],
                "spec_params": {},
                "quantity": 100,
                "unit": "kg",
            },
        )
    ).json()
    order2 = (
        await client.post(
            "/api/orders",
            json={
                "customer_id": cust["id"],
                "product_id": prod["id"],
                "spec_params": {},
                "quantity": 200,
                "unit": "kg",
            },
        )
    ).json()

    assert order1["order_no"].startswith("ORD-")
    serial1 = int(order1["order_no"].rsplit("-", 1)[1])
    serial2 = int(order2["order_no"].rsplit("-", 1)[1])
    assert serial2 == serial1 + 1
    assert order1["status"] == "PENDING"


async def test_order_no_is_not_reused_after_delete(client):
    prod = await _make_product(client)
    cust = await _make_customer(client)
    payload = {
        "customer_id": cust["id"],
        "product_id": prod["id"],
        "spec_params": {},
        "quantity": 100,
        "unit": "kg",
    }
    first = (await client.post("/api/orders", json=payload)).json()
    await client.delete(f"/api/orders/{first['id']}")
    second = (await client.post("/api/orders", json=payload)).json()

    assert second["order_no"] != first["order_no"]
    assert int(second["order_no"].rsplit("-", 1)[1]) > int(first["order_no"].rsplit("-", 1)[1])


async def test_create_order_snapshots_formula(client):
    prod = await _make_product(client)
    cust = await _make_customer(client)
    formula = (
        await client.post(
            "/api/formulas",
            json={
                "name": "配方A",
                "product_id": prod["id"],
                "spec_params": {"厚度": "50um"},
                "materials": "树脂60%",
            },
        )
    ).json()

    order = (
        await client.post(
            "/api/orders",
            json={
                "customer_id": cust["id"],
                "product_id": prod["id"],
                "spec_params": {},
                "quantity": 100,
                "unit": "kg",
                "formula_id": formula["id"],
            },
        )
    ).json()

    assert order["formula_snapshot"]["name"] == "配方A"
    assert order["formula_snapshot"]["materials"] == "树脂60%"

    # Snapshot is frozen at creation time — later formula edits shouldn't retroactively change it
    await client.put(
        f"/api/formulas/{formula['id']}",
        json={
            "name": "配方A改",
            "product_id": prod["id"],
            "spec_params": {},
            "materials": "树脂70%",
        },
    )
    reloaded = (await client.get(f"/api/orders/{order['id']}")).json()
    assert reloaded["formula_snapshot"]["materials"] == "树脂60%"


async def test_create_order_from_draft_creates_new_formula_and_order_atomically(client):
    product = await _make_product(client)
    customer = await _make_customer(client)

    response = await client.post(
        "/api/orders/from-draft",
        json={
            "customer_id": customer["id"],
            "product_id": product["id"],
            "spec_params": {"厚度": "50μm", "宽度": "600mm"},
            "quantity": "500",
            "unit": "kg",
            "formula_mode": "new",
            "new_formula_name": "录单新配方",
            "new_formula_materials": "树脂 100%",
        },
    )

    assert response.status_code == 201, response.text
    order = response.json()
    assert order["formula_id"]
    assert order["formula_snapshot"]["materials"] == "树脂 100%"
    formulas = (await client.get("/api/formulas")).json()
    assert any(
        formula["id"] == order["formula_id"] and formula["name"] == "录单新配方"
        for formula in formulas
    )


async def test_invalid_draft_does_not_leave_an_orphan_formula(client):
    product = await _make_product(client)
    before = (await client.get("/api/formulas")).json()

    response = await client.post(
        "/api/orders/from-draft",
        json={
            "customer_id": "missing-customer",
            "product_id": product["id"],
            "quantity": "500",
            "unit": "kg",
            "formula_mode": "new",
            "new_formula_name": "不应保留的配方",
        },
    )

    assert response.status_code == 409
    after = (await client.get("/api/formulas")).json()
    assert {formula["id"] for formula in after} == {formula["id"] for formula in before}


async def test_assigned_order_cannot_bypass_production_flow(client):
    prod = await _make_product(client)
    cust = await _make_customer(client)
    machine = (
        await client.post(
            "/api/machines",
            json={
                "name": "1号机",
                "min_width": 100,
                "max_width": 1200,
                "category_ids": [prod["category_id"]],
            },
        )
    ).json()
    order = (
        await client.post(
            "/api/orders",
            json={
                "customer_id": cust["id"],
                "product_id": prod["id"],
                "spec_params": {"宽度": "400mm"},
                "quantity": 100,
                "unit": "kg",
            },
        )
    ).json()
    await client.post("/api/production-tasks", json={"machine_id": machine["id"], "order_ids": [order["id"]]})

    reloaded = (await client.get(f"/api/orders/{order['id']}")).json()
    assert reloaded["task_id"] is not None

    res = await client.put(f"/api/orders/{order['id']}", json={"status": "PENDING"})
    assert res.status_code == 409
    unchanged = (await client.get(f"/api/orders/{order['id']}")).json()
    assert unchanged["status"] == "PRODUCING"
    assert unchanged["task_id"] == reloaded["task_id"]

    delete = await client.delete(f"/api/orders/{order['id']}")
    assert delete.status_code == 409

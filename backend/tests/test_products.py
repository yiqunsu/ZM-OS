async def test_create_product_requires_name_and_category(client):
    res = await client.post("/api/products", json={"name": "", "category_id": ""})
    assert res.status_code == 400


async def test_delete_product_blocked_when_formula_exists(client):
    cat = (await client.post("/api/product-categories", json={"name": "PE膜"})).json()
    prod = (await client.post("/api/products", json={"name": "透明膜", "category_id": cat["id"]})).json()
    await client.post("/api/formulas", json={
        "name": "配方A", "product_id": prod["id"], "spec_params": {}, "materials": "树脂60%",
    })

    res = await client.delete(f"/api/products/{prod['id']}")
    assert res.status_code == 409


async def test_delete_product_blocked_when_orders_exist(client):
    cat = (await client.post("/api/product-categories", json={"name": "PE膜"})).json()
    prod = (await client.post("/api/products", json={"name": "透明膜", "category_id": cat["id"]})).json()
    cust = (await client.post("/api/customers", json={"company": "华兴包装", "contact": "张三"})).json()
    await client.post("/api/orders", json={
        "customer_id": cust["id"], "product_id": prod["id"], "spec_params": {}, "quantity": 100, "unit": "kg",
    })

    res = await client.delete(f"/api/products/{prod['id']}")
    assert res.status_code == 409


async def test_delete_product_succeeds_when_unused(client):
    cat = (await client.post("/api/product-categories", json={"name": "PE膜"})).json()
    prod = (await client.post("/api/products", json={"name": "透明膜", "category_id": cat["id"]})).json()
    res = await client.delete(f"/api/products/{prod['id']}")
    assert res.status_code == 204

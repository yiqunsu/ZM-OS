async def _make_product(client):
    cat = (await client.post("/api/product-categories", json={"name": "PE膜"})).json()
    return (await client.post("/api/products", json={"name": "透明膜", "category_id": cat["id"]})).json()


async def test_delete_formula_blocked_when_order_references_it(client):
    prod = await _make_product(client)
    formula = (await client.post("/api/formulas", json={
        "name": "配方A", "product_id": prod["id"], "spec_params": {"厚度": "50um"}, "materials": "树脂60%",
    })).json()
    cust = (await client.post("/api/customers", json={"company": "华兴包装", "contact": "张三"})).json()
    await client.post("/api/orders", json={
        "customer_id": cust["id"], "product_id": prod["id"], "spec_params": {}, "quantity": 100, "unit": "kg",
        "formula_id": formula["id"],
    })

    res = await client.delete(f"/api/formulas/{formula['id']}")
    assert res.status_code == 409


async def test_delete_formula_unlinks_derived_formulas(client):
    prod = await _make_product(client)
    source = (await client.post("/api/formulas", json={
        "name": "原配方", "product_id": prod["id"], "spec_params": {}, "materials": "树脂60%",
    })).json()
    derived = (await client.post("/api/formulas", json={
        "name": "衍生配方", "product_id": prod["id"], "spec_params": {}, "materials": "树脂65%",
        "source_id": source["id"],
    })).json()
    assert derived["source"]["id"] == source["id"]

    res = await client.delete(f"/api/formulas/{source['id']}")
    assert res.status_code == 204

    formulas = (await client.get("/api/formulas")).json()
    reloaded = next(f for f in formulas if f["id"] == derived["id"])
    assert reloaded["source_id"] is None

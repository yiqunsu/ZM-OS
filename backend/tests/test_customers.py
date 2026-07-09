async def test_create_customer_requires_company_and_contact(client):
    res = await client.post("/api/customers", json={"company": "华兴包装", "contact": ""})
    assert res.status_code == 400


async def test_create_update_customer(client):
    created = (await client.post(
        "/api/customers", json={"company": "华兴包装", "contact": "张三"}
    )).json()

    res = await client.put(
        f"/api/customers/{created['id']}",
        json={"company": "华兴包装有限公司", "contact": "李四", "notes": "账期30天"},
    )
    assert res.status_code == 200
    assert res.json()["company"] == "华兴包装有限公司"
    assert res.json()["notes"] == "账期30天"


async def test_delete_customer_blocked_when_orders_exist(client):
    cust = (await client.post("/api/customers", json={"company": "华兴包装", "contact": "张三"})).json()
    cat = (await client.post("/api/product-categories", json={"name": "PE膜"})).json()
    prod = (await client.post("/api/products", json={"name": "透明膜", "category_id": cat["id"]})).json()
    await client.post("/api/orders", json={
        "customer_id": cust["id"], "product_id": prod["id"],
        "spec_params": {}, "quantity": 100, "unit": "kg",
    })

    res = await client.delete(f"/api/customers/{cust['id']}")
    assert res.status_code == 409

async def test_create_category_requires_name(client):
    res = await client.post("/api/product-categories", json={"name": "  "})
    assert res.status_code == 400


async def test_create_and_list_category(client):
    res = await client.post("/api/product-categories", json={"name": "PE膜", "desc": "拉伸膜"})
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "PE膜"

    res = await client.get("/api/product-categories")
    names = [c["name"] for c in res.json()]
    assert "PE膜" in names


async def test_delete_category_blocked_when_products_exist(client):
    cat = (await client.post("/api/product-categories", json={"name": "PE膜"})).json()
    await client.post("/api/products", json={"name": "透明膜", "category_id": cat["id"]})

    res = await client.delete(f"/api/product-categories/{cat['id']}")
    assert res.status_code == 409


async def test_delete_category_succeeds_when_empty(client):
    cat = (await client.post("/api/product-categories", json={"name": "PE膜"})).json()
    res = await client.delete(f"/api/product-categories/{cat['id']}")
    assert res.status_code == 204

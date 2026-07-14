"""Agent tests that don't need an LLM key: skill routing, tool schemas, and the
read/write tool executors against the test DB.

The tools deliberately open their own `async_session` (the SSE generator outlives
the request-scoped session), so here we point that sessionmaker at the test DB and
clean up manually rather than relying on the transactional-rollback fixture.
"""

import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.agent.skills as skills_mod
import app.agent.tools as tools_mod
from app.agent import skills, tools
from app.models import Customer, Machine, Order, Product, ProductCategory

TEST_DB_URL = "postgresql+asyncpg://filmos:filmos@localhost:5432/filmos_test"


@pytest_asyncio.fixture
async def agent_db(monkeypatch):
    engine = create_async_engine(TEST_DB_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(tools_mod, "async_session", maker)
    monkeypatch.setattr(skills_mod, "async_session", maker)
    created: dict[str, list[str]] = {
        "orders": [], "products": [], "customers": [], "categories": [], "machines": []
    }
    yield maker, created
    # cleanup in FK-safe order
    async with maker() as db:
        for oid in created["orders"]:
            await db.execute(delete(Order).where(Order.id == oid))
        for pid in created["products"]:
            await db.execute(delete(Product).where(Product.id == pid))
        for cid in created["customers"]:
            await db.execute(delete(Customer).where(Customer.id == cid))
        for mid in created["machines"]:
            await db.execute(delete(Machine).where(Machine.id == mid))
        for cid in created["categories"]:
            await db.execute(delete(ProductCategory).where(ProductCategory.id == cid))
        await db.commit()
    await engine.dispose()


# ─── Skill routing (pure, no DB) ────────────────────────────────────────────


def test_skill_routing_create_order():
    assert skills.resolve_skill("帮我录一张订单").name == "create-order"
    assert skills.resolve_skill("有个新订单帮我建单").name == "create-order"


def test_skill_routing_schedule():
    assert skills.resolve_skill("帮我排一下今天的单").name == "schedule"
    assert skills.resolve_skill("把这单放到3号机").name == "schedule"


def test_skill_routing_general_fallback():
    assert skills.resolve_skill("华兴的联系方式是多少").name == "general"


def test_create_order_skill_restricts_tools():
    s = skills.resolve_skill("录单")
    assert "confirm_and_create_order" in s.allowed_tools
    assert "confirm_and_execute" not in s.allowed_tools  # scheduling tool not exposed


def test_tool_schemas_cover_all_names():
    names = {t["function"]["name"] for t in tools.TOOL_SCHEMAS}
    assert "confirm_and_create_order" in names
    assert tools.WRITE_TOOLS <= names


# ─── Read tools against test DB ─────────────────────────────────────────────


async def test_query_customer_fuzzy_match(agent_db):
    maker, created = agent_db
    async with maker() as db:
        c = Customer(company="华兴包装", contact="张三")
        db.add(c)
        await db.commit()
        created["customers"].append(c.id)

    res = await tools.run_read_tool("query_customer", {"keyword": "华兴"})
    assert any(r["company"] == "华兴包装" for r in res)


async def test_get_pending_orders(agent_db):
    maker, created = agent_db
    async with maker() as db:
        cat = ProductCategory(name="PE膜")
        db.add(cat)
        await db.flush()
        prod = Product(name="透明膜", category_id=cat.id)
        cust = Customer(company="测试客户A", contact="李四")
        db.add_all([prod, cust])
        await db.flush()
        order = Order(
            order_no="ORD-TEST-001", customer_id=cust.id, product_id=prod.id,
            spec_params={"厚度": "50um"}, quantity=100, unit="kg", status="PENDING",
        )
        db.add(order)
        await db.commit()
        created["categories"].append(cat.id)
        created["products"].append(prod.id)
        created["customers"].append(cust.id)
        created["orders"].append(order.id)

    res = await tools.run_read_tool("get_pending_orders", {})
    assert any(o["order_no"] == "ORD-TEST-001" for o in res)


async def test_inference_tools_return_empty(agent_db):
    assert await tools.run_read_tool("extract_order_info", {"raw_text": "x"}) == {}
    assert await tools.run_read_tool("check_unfinished_task", {}) == {}


# ─── Write tool executor ────────────────────────────────────────────────────


async def test_run_write_tool_creates_order(agent_db):
    maker, created = agent_db
    async with maker() as db:
        cat = ProductCategory(name="PE膜")
        db.add(cat)
        await db.flush()
        prod = Product(name="透明膜", category_id=cat.id)
        cust = Customer(company="测试客户B", contact="王五")
        db.add_all([prod, cust])
        await db.commit()
        created["categories"].append(cat.id)
        created["products"].append(prod.id)
        created["customers"].append(cust.id)

    result = await tools.run_write_tool(
        "confirm_and_create_order",
        {
            "customer_id": cust.id, "product_id": prod.id,
            "spec_params": {"厚度": "50um"}, "quantity": 300, "unit": "kg",
        },
    )
    assert result["success"] is True
    assert result["order_no"].startswith("ORD-")

    async with maker() as db:
        from sqlalchemy import select
        oid = (await db.execute(select(Order.id).where(Order.order_no == result["order_no"]))).scalar_one()
        created["orders"].append(oid)

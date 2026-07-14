"""Load a realistic demo dataset for local testing.

This is NOT part of the schema migrations and is never run automatically — it's a
manual convenience for exercising the app (kanban, scheduling, the agent) against
believable data. Do not run it against a production database.

Usage (from the backend container or local venv):
    python scripts/seed_demo.py           # seed only if the DB looks empty
    python scripts/seed_demo.py --reset   # wipe business data first, then seed
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, func, select  # noqa: E402

from app.core.database import async_session  # noqa: E402
from app.models import (  # noqa: E402
    Customer,
    Formula,
    Machine,
    MachineCategory,
    MachinePattern,
    Order,
    Pattern,
    Product,
    ProductCategory,
    ProductionTask,
)
from app.models.order import OrderStatus  # noqa: E402

# ─── 演示数据定义 ───────────────────────────────────────────────────────────────

CATEGORIES = [
    ("PE膜", "聚乙烯薄膜"),
    ("PP膜", "聚丙烯薄膜"),
    ("CPE膜", "流延聚乙烯膜"),
]

PATTERNS = [
    ("光面", "表面光滑无纹理"),
    ("磨砂", "哑光磨砂表面"),
    ("压花", "规则压花纹理"),
]

# 产品：(名称, 所属大类名)
PRODUCTS = [
    ("透明PE拉伸膜", "PE膜"),
    ("PE自粘保护膜", "PE膜"),
    ("BOPP珠光膜", "PP膜"),
    ("CPP消光膜", "PP膜"),
    ("CPE磨砂膜", "CPE膜"),
]

# 客户：(公司, 联系人, 备注)
CUSTOMERS = [
    ("华兴包装", "张伟", "账期30天，走顺丰"),
    ("华东纸业", "李强", None),
    ("明光塑业", "王芳", None),
    ("恒达电子", "刘洋", "要求无尘车间生产"),
]

# 机器：(名称, 是否在用, 最小宽, 最大宽, 备注, 可生产大类名, 可用花纹名)
MACHINES = [
    ("1号机", True, 100, 1200, "主力机，稳定", ["PE膜", "CPE膜"], ["光面", "磨砂"]),
    ("2号机", True, 200, 1600, None, ["PP膜"], ["光面", "压花"]),
    ("3号机", True, 300, 800, "窄幅专用", ["PE膜"], ["磨砂"]),
    ("4号机", False, 100, 1000, "检修中，暂停", ["PE膜", "PP膜"], ["光面"]),
]

# 配方：(名称, 产品名, spec_params dict, materials 文本)
FORMULAS = [
    ("PE-50透明-标准", "透明PE拉伸膜", {"厚度": "50μm", "宽度": "600mm"},
     "LDPE树脂 70%\nLLDPE 25%\n爽滑剂 5%"),
    ("PE-40自粘", "PE自粘保护膜", {"厚度": "40μm", "宽度": "500mm"},
     "LLDPE 80%\n自粘母料 15%\n抗静电剂 5%"),
    ("CPE-60磨砂", "CPE磨砂膜", {"厚度": "60μm", "宽度": "400mm"},
     "CPE树脂 85%\n消光母料 10%\n开口剂 5%"),
]

# 订单：(客户公司, 产品名, spec_params, 数量, 单位, 配方名 or None, 额外要求)
ORDERS = [
    ("华兴包装", "透明PE拉伸膜", {"厚度": "50μm", "宽度": "600mm"}, 500, "kg", "PE-50透明-标准", None),
    ("华东纸业", "CPE磨砂膜", {"厚度": "60μm", "宽度": "400mm"}, 300, "kg", "CPE-60磨砂", "交期本周五"),
    ("明光塑业", "BOPP珠光膜", {"厚度": "30μm", "宽度": "800mm"}, 1, "t", None, None),
    ("恒达电子", "PE自粘保护膜", {"厚度": "40μm", "宽度": "500mm"}, 800, "kg", "PE-40自粘", "无尘包装"),
    ("华兴包装", "透明PE拉伸膜", {"厚度": "50μm", "宽度": "500mm"}, 400, "kg", "PE-50透明-标准", None),
]

_BUSINESS_TABLES = [
    (Order, "orders"),
    (ProductionTask, "production_tasks"),
    (Formula, "formulas"),
    (MachineCategory, "machine_categories"),
    (MachinePattern, "machine_patterns"),
    (Machine, "machines"),
    (Product, "products"),
    (Pattern, "patterns"),
    (ProductCategory, "product_categories"),
    (Customer, "customers"),
]


async def _is_seeded(db) -> bool:
    count = await db.scalar(select(func.count()).select_from(Customer))
    return bool(count)


async def _wipe(db) -> None:
    # FK-safe order: orders → tasks → formulas → link tables → machines/products → …
    for model, _ in _BUSINESS_TABLES:
        await db.execute(delete(model))
    await db.commit()


async def seed(reset: bool) -> None:
    async with async_session() as db:
        if await _is_seeded(db):
            if not reset:
                print("数据库已有业务数据，跳过。加 --reset 可清空后重灌演示数据。")
                return
            print("清空现有业务数据…")
            await _wipe(db)

        # 大类
        cats: dict[str, ProductCategory] = {}
        for name, desc in CATEGORIES:
            c = ProductCategory(name=name, desc=desc)
            db.add(c)
            cats[name] = c

        # 花纹
        pats: dict[str, Pattern] = {}
        for name, desc in PATTERNS:
            p = Pattern(name=name, desc=desc)
            db.add(p)
            pats[name] = p
        await db.flush()

        # 产品
        prods: dict[str, Product] = {}
        for name, cat_name in PRODUCTS:
            p = Product(name=name, category_id=cats[cat_name].id)
            db.add(p)
            prods[name] = p

        # 客户
        custs: dict[str, Customer] = {}
        for company, contact, notes in CUSTOMERS:
            c = Customer(company=company, contact=contact, notes=notes)
            db.add(c)
            custs[company] = c

        # 机器 + 关联
        for name, active, mn, mx, notes, cat_names, pat_names in MACHINES:
            m = Machine(name=name, is_active=active, min_width=mn, max_width=mx, notes=notes)
            db.add(m)
            await db.flush()
            for cn in cat_names:
                db.add(MachineCategory(machine_id=m.id, category_id=cats[cn].id))
            for pn in pat_names:
                db.add(MachinePattern(machine_id=m.id, pattern_id=pats[pn].id))
        await db.flush()

        # 配方
        formulas: dict[str, Formula] = {}
        for name, prod_name, spec, materials in FORMULAS:
            f = Formula(
                name=name, product_id=prods[prod_name].id,
                spec_params=spec, materials=materials,
            )
            db.add(f)
            formulas[name] = f
        await db.flush()

        # 订单（全部 PENDING，方便演示排单）
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        for i, (company, prod_name, spec, qty, unit, formula_name, notes) in enumerate(ORDERS, 1):
            formula = formulas.get(formula_name) if formula_name else None
            snapshot = None
            if formula is not None:
                snapshot = {
                    "name": formula.name,
                    "spec_params": formula.spec_params,
                    "materials": formula.materials,
                }
            db.add(
                Order(
                    order_no=f"ORD-{today}-{i:03d}",
                    customer_id=custs[company].id,
                    product_id=prods[prod_name].id,
                    spec_params=spec,
                    quantity=qty,
                    unit=unit,
                    formula_id=formula.id if formula else None,
                    formula_snapshot=snapshot,
                    extra_notes=notes,
                    status=OrderStatus.PENDING,
                )
            )

        await db.commit()
        print(
            f"演示数据已灌入：{len(CATEGORIES)} 大类 / {len(PRODUCTS)} 产品 / "
            f"{len(CUSTOMERS)} 客户 / {len(MACHINES)} 机器 / {len(FORMULAS)} 配方 / "
            f"{len(ORDERS)} 待排单订单。"
        )


if __name__ == "__main__":
    asyncio.run(seed(reset="--reset" in sys.argv))

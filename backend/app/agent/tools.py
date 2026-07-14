"""Agent tool schemas + execution.

Tools are dispatched by name. Read tools run queries and feed results back to
the model; write tools are gated behind a human-in-the-loop interrupt and only
run on confirm. Each executor opens its own short-lived DB session so the graph
never has to thread a request-scoped session through its state.

Ported from the original TS `route.ts` runReadTool / runWriteTool / enrich.
"""

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.core.database import async_session
from app.models import (
    Customer,
    Formula,
    Machine,
    Order,
    Product,
    ProductionTask,
)
from app.models.order import OrderStatus
from app.models.production import TaskStatus
from app.services import order_service, production_service

# ─── Tool 定义（绑定给 LLM 的 JSON schema）──────────────────────────────────────

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "extract_order_info",
            "description": (
                "从老板粘贴的微信消息或口语描述中提取结构化订单字段。老板输入原始文字时调用此工具，"
                "解析出客户名、产品名、规格参数、数量、单位等信息。字段不确定时返回 null，不要猜测。"
            ),
            "parameters": {
                "type": "object",
                "properties": {"raw_text": {"type": "string", "description": "老板粘贴或输入的原始文字"}},
                "required": ["raw_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_customer",
            "description": "在客户库中模糊搜索客户。当需要匹配老板提到的客户名称时调用。返回匹配度最高的客户列表。",
            "parameters": {
                "type": "object",
                "properties": {"keyword": {"type": "string", "description": "客户名称关键词，如「华兴」"}},
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_product",
            "description": "在产品库中搜索匹配的产品。当老板提到产品名称（如「PE膜」）时调用，返回匹配产品列表。",
            "parameters": {
                "type": "object",
                "properties": {"keyword": {"type": "string", "description": "产品名称关键词，如「PE膜」"}},
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_formula",
            "description": "查询指定产品下的配方列表。当老板选择从配方库选择配方时调用，需要先确定产品 ID。",
            "parameters": {
                "type": "object",
                "properties": {"product_id": {"type": "string", "description": "产品 ID"}},
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_and_create_order",
            "description": (
                "创建新订单。所有必填字段（客户、产品、规格参数、数量、单位）收集完毕后，老板确认摘要卡片后才调用。"
                "这是写操作，调用后系统会显示确认卡片等待老板最终确认。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string", "description": "客户 ID"},
                    "product_id": {"type": "string", "description": "产品 ID"},
                    "spec_params": {
                        "type": "object",
                        "description": '规格参数，如 {"厚度": "50μm", "宽度": "600mm"}',
                        "additionalProperties": {"type": "string"},
                    },
                    "quantity": {"type": "number", "description": "数量"},
                    "unit": {"type": "string", "enum": ["kg", "t"], "description": "单位"},
                    "formula_id": {"type": "string", "description": "配方 ID（可选）"},
                    "extra_notes": {"type": "string", "description": "额外要求或备注（可选）"},
                },
                "required": ["customer_id", "product_id", "spec_params", "quantity", "unit"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_order",
            "description": "修改已有订单的字段。这是写操作，调用后系统会显示确认卡片等待老板确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单 ID"},
                    "fields": {
                        "type": "object",
                        "description": "要更新的字段：spec_params、quantity、unit、formula_id、extra_notes、status",
                        "additionalProperties": True,
                    },
                },
                "required": ["order_id", "fields"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pending_orders",
            "description": "获取所有状态为「待排单」的订单列表。发起排单任务时首先调用。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_machine_status",
            "description": "获取所有机器的当前状态，包括机器规格和当前生产队列。生成排单方案前调用。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_schedule_plan",
            "description": (
                "根据选定的待排单订单和机器状态，生成排单方案。综合考虑：机器产品类别匹配、宽度限制、"
                "合并生产可能性、接单时间顺序。方案需包含每个决策的原因说明。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "本次要排单的订单 ID 列表",
                    }
                },
                "required": ["order_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "adjust_schedule_plan",
            "description": "根据老板的对话指令调整当前排单方案。返回调整后的完整方案和变更说明。",
            "parameters": {
                "type": "object",
                "properties": {
                    "current_plan": {"type": "object", "description": "当前排单方案"},
                    "instruction": {"type": "string", "description": "老板的调整指令"},
                },
                "required": ["current_plan", "instruction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_and_execute",
            "description": (
                "执行最终排单方案，在数据库中创建生产任务并关联订单。老板确认方案后才调用。"
                "这是写操作，调用后系统会显示确认卡片等待老板最终确认。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "plan": {
                        "type": "object",
                        "properties": {
                            "tasks": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "machine_id": {"type": "string"},
                                        "machine_name": {"type": "string"},
                                        "order_ids": {"type": "array", "items": {"type": "string"}},
                                        "order_nos": {"type": "array", "items": {"type": "string"}},
                                    },
                                    "required": ["machine_id", "order_ids"],
                                },
                            }
                        },
                        "required": ["tasks"],
                    }
                },
                "required": ["plan"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_unfinished_task",
            "description": "检查当前对话中是否有未完成的录单或排单任务。检测到意图切换时调用。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

# 需要老板确认才能执行的写操作
WRITE_TOOLS: set[str] = {"confirm_and_create_order", "update_order", "confirm_and_execute"}

# 纯 AI 推理型工具：无需查库，返回空对象让模型基于上下文推理
_INFERENCE_TOOLS = {
    "extract_order_info",
    "generate_schedule_plan",
    "adjust_schedule_plan",
    "check_unfinished_task",
}

ALL_TOOL_NAMES = [t["function"]["name"] for t in TOOL_SCHEMAS]


def schemas_for(allowed: list[str]) -> list[dict[str, Any]]:
    return [t for t in TOOL_SCHEMAS if t["function"]["name"] in allowed]


# ─── 读操作执行 ─────────────────────────────────────────────────────────────────


async def run_read_tool(name: str, args: dict[str, Any]) -> Any:
    if name in _INFERENCE_TOOLS:
        return {}

    async with async_session() as db:
        if name == "query_customer":
            keyword = str(args.get("keyword") or "")
            result = await db.execute(
                select(Customer)
                .where(or_(Customer.company.contains(keyword), Customer.contact.contains(keyword)))
                .order_by(Customer.company)
                .limit(5)
            )
            return [
                {"id": c.id, "company": c.company, "contact": c.contact, "notes": c.notes}
                for c in result.scalars().all()
            ]

        if name == "query_product":
            keyword = str(args.get("keyword") or "")
            stmt = select(Product).options(selectinload(Product.category)).order_by(Product.name).limit(30)
            if keyword:
                stmt = stmt.where(Product.name.contains(keyword))
            result = await db.execute(stmt)
            return [
                {
                    "id": p.id,
                    "name": p.name,
                    "category_id": p.category_id,
                    "category_name": p.category.name,
                }
                for p in result.scalars().all()
            ]

        if name == "query_formula":
            product_id = str(args.get("product_id") or "")
            result = await db.execute(
                select(Formula)
                .where(Formula.product_id == product_id)
                .order_by(Formula.created_at.desc())
                .limit(10)
            )
            return [
                {"id": f.id, "name": f.name, "spec_params": f.spec_params, "notes": f.notes}
                for f in result.scalars().all()
            ]

        if name == "get_pending_orders":
            result = await db.execute(
                select(Order)
                .where(Order.status == OrderStatus.PENDING)
                .order_by(Order.created_at.asc())
                .options(
                    selectinload(Order.customer),
                    selectinload(Order.product).selectinload(Product.category),
                )
            )
            return [
                {
                    "id": o.id,
                    "order_no": o.order_no,
                    "customer": f"{o.customer.company}·{o.customer.contact}",
                    "product": o.product.name,
                    "category": o.product.category.name,
                    "spec_params": o.spec_params,
                    "quantity": o.quantity,
                    "unit": o.unit,
                }
                for o in result.scalars().all()
            ]

        if name == "get_machine_status":
            from app.models import MachineCategory

            result = await db.execute(
                select(Machine)
                .where(Machine.is_active.is_(True))
                .options(
                    selectinload(Machine.category_links).selectinload(MachineCategory.category),
                    selectinload(Machine.tasks).selectinload(ProductionTask.orders).selectinload(
                        Order.customer
                    ),
                    selectinload(Machine.tasks).selectinload(ProductionTask.orders).selectinload(
                        Order.product
                    ),
                )
            )
            machines = result.scalars().all()
            out = []
            for m in machines:
                active_tasks = [t for t in m.tasks if t.status != TaskStatus.DONE]
                active_tasks.sort(key=lambda t: t.position)
                out.append(
                    {
                        "id": m.id,
                        "name": m.name,
                        "min_width": m.min_width,
                        "max_width": m.max_width,
                        "notes": m.notes,
                        "categories": [link.category.name for link in m.category_links],
                        "current_tasks": [
                            {
                                "id": t.id,
                                "position": t.position,
                                "status": t.status.value,
                                "orders": [
                                    {
                                        "order_no": o.order_no,
                                        "customer": o.customer.company,
                                        "product": o.product.name,
                                        "spec_params": o.spec_params,
                                        "quantity": f"{o.quantity}{o.unit}",
                                    }
                                    for o in t.orders
                                ],
                            }
                            for t in active_tasks
                        ],
                    }
                )
            return out

    raise ValueError(f"未知的读操作 Tool: {name}")


# ─── 写操作执行（由 /confirm 恢复图后调用）───────────────────────────────────────


async def run_write_tool(name: str, args: dict[str, Any]) -> Any:
    async with async_session() as db:
        if name == "confirm_and_create_order":
            order = await order_service.create_order(
                db,
                customer_id=str(args["customer_id"]),
                product_id=str(args["product_id"]),
                spec_params=args.get("spec_params") or {},
                quantity=float(args["quantity"]),
                unit=str(args["unit"]),
                formula_id=str(args["formula_id"]) if args.get("formula_id") else None,
                extra_notes=str(args["extra_notes"]) if args.get("extra_notes") else None,
            )
            return {
                "success": True,
                "order_no": order.order_no,
                "customer": f"{order.customer.company}·{order.customer.contact}",
                "product": order.product.name,
                "quantity": f"{order.quantity}{order.unit}",
            }

        if name == "update_order":
            order_id = str(args["order_id"])
            fields = args.get("fields") or {}
            updated = await order_service.update_order(db, order_id, fields)
            return {"success": True, "order_no": updated.order_no}

        if name == "confirm_and_execute":
            plan = args["plan"]
            results = []
            for task in plan["tasks"]:
                created = await production_service.create_task(
                    db, task["machine_id"], task["order_ids"]
                )
                results.append({"task_id": created.id, "order_count": len(task["order_ids"])})
            return {"success": True, "tasks_created": len(results), "tasks": results}

    raise ValueError(f"未知的写操作 Tool: {name}")


# ─── 确认卡片展示数据 ───────────────────────────────────────────────────────────


async def enrich_for_display(name: str, args: dict[str, Any]) -> dict[str, Any]:
    async with async_session() as db:
        if name == "confirm_and_create_order":
            customer = await db.get(Customer, str(args.get("customer_id") or ""))
            product = await db.get(Product, str(args.get("product_id") or ""))
            product_cat = None
            if product is not None:
                product = await db.get(Product, product.id)
                await db.refresh(product, ["category"])
                product_cat = product.category.name
            formula = None
            if args.get("formula_id"):
                formula = await db.get(Formula, str(args["formula_id"]))
            return {
                "customer": f"{customer.company}·{customer.contact}" if customer else args.get("customer_id"),
                "product": f"{product_cat} / {product.name}" if product else args.get("product_id"),
                "spec_params": args.get("spec_params") or {},
                "quantity": args.get("quantity"),
                "unit": args.get("unit"),
                "formula_name": formula.name if formula else None,
                "formula_notes": formula.notes if formula else None,
                "extra_notes": args.get("extra_notes"),
            }

        if name == "update_order":
            order = await db.get(Order, str(args.get("order_id") or ""))
            company = ""
            if order is not None:
                await db.refresh(order, ["customer"])
                company = order.customer.company
            return {
                "order_no": order.order_no if order else args.get("order_id"),
                "customer": company,
                "changes": args.get("fields"),
            }

        if name == "confirm_and_execute":
            plan = args.get("plan") or {}
            tasks = plan.get("tasks") or []
            enriched = []
            for t in tasks:
                machine = await db.get(Machine, t.get("machine_id", ""))
                order_nos = t.get("order_nos")
                if not order_nos:
                    result = await db.execute(
                        select(Order.order_no).where(Order.id.in_(t.get("order_ids", [])))
                    )
                    order_nos = [row[0] for row in result.all()]
                enriched.append(
                    {
                        "machine_name": machine.name if machine else t.get("machine_id"),
                        "order_ids": t.get("order_ids", []),
                        "order_nos": order_nos,
                    }
                )
            return {
                "task_count": len(enriched),
                "order_count": sum(len(t["order_ids"]) for t in enriched),
                "tasks": enriched,
            }

    return dict(args)


async def _count_pending() -> int:
    async with async_session() as db:
        return await db.scalar(
            select(func.count()).select_from(Order).where(Order.status == OrderStatus.PENDING)
        ) or 0

"""Skill routing: intent → task prompt + restricted toolset + optional context.

Stage-one keyword matching (zero latency / cost), matching the original TS
`skills/router.ts`. Falls back to the general skill, which exposes all tools.
"""

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agent import prompts
from app.core.database import async_session
from app.models import Customer, Product


@dataclass
class Skill:
    name: str
    task_prompt: str
    allowed_tools: list[str]
    loads_context: bool = False


CREATE_ORDER = Skill(
    name="create-order",
    task_prompt=prompts.CREATE_ORDER_PROMPT,
    allowed_tools=[
        "extract_order_info",
        "query_customer",
        "query_product",
        "query_formula",
        "confirm_and_create_order",
        "check_unfinished_task",
    ],
    loads_context=True,
)

SCHEDULE = Skill(
    name="schedule",
    task_prompt=prompts.SCHEDULE_PROMPT,
    allowed_tools=[
        "get_pending_orders",
        "get_machine_status",
        "generate_schedule_plan",
        "adjust_schedule_plan",
        "confirm_and_execute",
        "check_unfinished_task",
    ],
)

GENERAL = Skill(
    name="general",
    task_prompt=prompts.GENERAL_PROMPT,
    allowed_tools=[
        "extract_order_info",
        "query_customer",
        "query_product",
        "query_formula",
        "confirm_and_create_order",
        "update_order",
        "get_pending_orders",
        "get_machine_status",
        "generate_schedule_plan",
        "adjust_schedule_plan",
        "confirm_and_execute",
        "check_unfinished_task",
    ],
)

_SKILLS = {s.name: s for s in (CREATE_ORDER, SCHEDULE, GENERAL)}

_KEYWORDS: list[tuple[str, list[re.Pattern]]] = [
    (
        "create-order",
        [
            re.compile(r"录单|录一张|新建订单|帮我录|帮我建单|下单|接单|建个单"),
            re.compile(r"有.*订单|订单.*帮我"),
        ],
    ),
    (
        "schedule",
        [
            re.compile(r"排单|排产|安排生产|生产计划|帮我排|机器.*安排"),
            re.compile(r"哪台机|放.*机|分配.*机器"),
        ],
    ),
]


def resolve_skill(text: str) -> Skill:
    for skill_name, patterns in _KEYWORDS:
        if any(p.search(text) for p in patterns):
            return _SKILLS[skill_name]
    return GENERAL


def get_skill(name: str) -> Skill:
    return _SKILLS.get(name, GENERAL)


async def load_context(skill: Skill) -> str:
    """Preload small master-data lists into the prompt so the create-order skill can
    match customers/products without extra tool round-trips."""
    if not skill.loads_context:
        return ""

    async with async_session() as db:
        customers = (
            (await db.execute(select(Customer).order_by(Customer.company))).scalars().all()
        )
        products = (
            (
                await db.execute(
                    select(Product).options(selectinload(Product.category)).order_by(Product.name)
                )
            )
            .scalars()
            .all()
        )

    customer_list = (
        "\n".join(f"  - {c.company}（{c.contact}）[id:{c.id}]" for c in customers)
        if customers
        else "  （暂无客户，如有需要可新建）"
    )
    product_list = (
        "\n".join(f"  - [{p.category.name}] {p.name}  [id:{p.id}]" for p in products)
        if products
        else "  （暂无产品）"
    )

    return f"\n【客户列表】\n{customer_list}\n\n【产品列表】\n{product_list}\n"

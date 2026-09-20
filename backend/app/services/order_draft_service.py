"""Draft validation and partial updates, composed by an atomic work-item use case."""

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer, Formula, Product
from app.schemas.agent.order_intake import OrderDraft
from app.services import agent_session_service as sessions
from app.services.order_specification import validate_specification


async def validate_draft(db: AsyncSession, draft: OrderDraft) -> list[dict]:
    issues = []

    def issue(field, code, message, severity="blocking"):
        issues.append(
            {"field": field, "code": code, "message": message, "severity": severity, "candidates": []}
        )

    for field, model, label in (("customer_id", Customer, "客户"), ("product_id", Product, "产品")):
        identifier = getattr(draft, field)
        if identifier is None or await db.get(model, identifier) is None:
            issue(field, "ENTITY_REQUIRED", f"请选择系统内已有的{label}")
    if draft.quantity is None:
        issue("quantity", "QUANTITY_REQUIRED", "请填写数量")
    if draft.unit is None:
        issue("unit", "UNIT_REQUIRED", "请选择数量单位")
    try:
        validate_specification(draft.spec_params)
    except HTTPException as error:
        issue("spec_params", "SPEC_INCOMPLETE", error.detail)
    if draft.formula_mode == "existing":
        formula = await db.get(Formula, draft.formula_id) if draft.formula_id else None
        if formula is None or formula.product_id != draft.product_id:
            issue("formula_id", "FORMULA_INCOMPATIBLE", "请选择与产品对应的已有配方")
    return issues


def merge_patch(draft: OrderDraft, patch: dict) -> OrderDraft:
    allowed = set(OrderDraft.model_fields) - {"schema_version"}
    if set(patch) - allowed:
        sessions.fail("INPUT_INVALID", "补丁包含不可修改的字段", 422)
    candidate = draft.model_dump()
    for key, value in patch.items():
        if key == "spec_params":
            if not isinstance(value, dict):
                sessions.fail("INPUT_INVALID", "规格补丁必须是字段对象", 422)
            specs = dict(candidate["spec_params"])
            for name, content in value.items():
                if content is None:
                    specs.pop(name, None)
                else:
                    specs[name] = content
            candidate[key] = specs
        else:
            candidate[key] = value
    if patch.get("formula_mode") == "none":
        candidate["formula_id"] = None
    try:
        return OrderDraft.model_validate(candidate)
    except ValidationError:
        sessions.fail("INPUT_INVALID", "草稿字段格式无效，请核对数量、单位或配方", 422)

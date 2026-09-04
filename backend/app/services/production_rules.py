"""Shared production compatibility rules for manual and Agent scheduling paths."""

import re
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from app.models import Machine, Order

_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
_WIDTH_KEYS = {"宽度", "width", "幅宽"}
_THICKNESS_KEYS = {"厚度", "thickness", "厚"}
_PATTERN_KEYS = {"花纹", "pattern", "纹路"}


@dataclass(frozen=True, slots=True)
class ProductionSignature:
    material: str | None
    category_id: str
    category_name: str
    thickness: str | None
    pattern: str

    @property
    def complete_for_merge(self) -> bool:
        return bool(self.material and self.thickness)


@dataclass(frozen=True, slots=True)
class OrderProductionProfile:
    order: Order
    width: float | None
    signature: ProductionSignature


def normalized_key(value: str) -> str:
    return value.strip().casefold().replace(" ", "")


def spec_value(spec_params: dict[str, Any], aliases: set[str]) -> str:
    normalized_aliases = {normalized_key(alias) for alias in aliases}
    for key, value in (spec_params or {}).items():
        if normalized_key(str(key)) in normalized_aliases and value is not None:
            return str(value).strip()
    return ""


def positive_number(value: str) -> float | None:
    match = _NUMBER_RE.search(value.replace(",", ""))
    if match is None:
        return None
    try:
        parsed = float(match.group())
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def production_signature(order: Order) -> ProductionSignature:
    snapshot = order.formula_snapshot or {}
    raw_material = str(order.formula_id or snapshot.get("materials") or "").strip()
    raw_thickness = spec_value(order.spec_params, _THICKNESS_KEYS)
    return ProductionSignature(
        material=raw_material or None,
        category_id=order.product.category_id,
        category_name=order.product.category.name,
        thickness=raw_thickness or None,
        pattern=spec_value(order.spec_params, _PATTERN_KEYS),
    )


def order_profile(order: Order) -> OrderProductionProfile:
    return OrderProductionProfile(
        order=order,
        width=positive_number(spec_value(order.spec_params, _WIDTH_KEYS)),
        signature=production_signature(order),
    )


def same_signature(left: ProductionSignature, right: ProductionSignature) -> bool:
    return (
        left.material,
        left.category_id,
        left.thickness,
        left.pattern.casefold(),
    ) == (
        right.material,
        right.category_id,
        right.thickness,
        right.pattern.casefold(),
    )


def validate_machine_batch(machine: Machine, orders: list[Order]) -> float:
    """Validate one production task and return its combined width.

    The caller must eager-load machine category/pattern links and each order's
    product/category before invoking this rule.
    """

    if not machine.is_active:
        raise HTTPException(409, f"机器“{machine.name}”已停用，不能接收新任务")
    if not orders:
        raise HTTPException(400, "生产任务至少需要一张订单")

    profiles = [order_profile(order) for order in orders]
    category_ids = {link.category_id for link in machine.category_links}
    unsupported_categories = {
        profile.signature.category_name
        for profile in profiles
        if profile.signature.category_id not in category_ids
    }
    if unsupported_categories:
        names = "、".join(sorted(unsupported_categories))
        raise HTTPException(409, f"机器“{machine.name}”不支持产品大类：{names}")

    pattern_names = {link.pattern.name.strip().casefold() for link in machine.pattern_links}
    unsupported_patterns = {
        profile.signature.pattern
        for profile in profiles
        if profile.signature.pattern
        and profile.signature.pattern.casefold() not in pattern_names
    }
    if unsupported_patterns:
        names = "、".join(sorted(unsupported_patterns))
        raise HTTPException(409, f"机器“{machine.name}”不具备花纹能力：{names}")

    missing_width_orders = [
        profile.order.order_no for profile in profiles if profile.width is None
    ]
    if missing_width_orders:
        raise HTTPException(409, f"订单 {missing_width_orders[0]} 缺少可识别的宽度")

    if len(profiles) > 1:
        incomplete = [
            profile.order.order_no
            for profile in profiles
            if not profile.signature.complete_for_merge
        ]
        if incomplete:
            raise HTTPException(
                409,
                f"订单 {incomplete[0]} 缺少配方/材料或厚度，不能与其他订单合并生产",
            )
        first_signature = profiles[0].signature
        if any(
            not same_signature(first_signature, profile.signature)
            for profile in profiles[1:]
        ):
            raise HTTPException(409, "合并订单的配方/材料、产品大类、厚度或花纹不一致")

    total_width = sum(profile.width or 0 for profile in profiles)
    if total_width < machine.min_width or total_width > machine.max_width:
        raise HTTPException(
            409,
            f"合并宽度 {total_width:g}mm 不在机器“{machine.name}”"
            f"允许范围 {machine.min_width:g}–{machine.max_width:g}mm 内",
        )
    return total_width

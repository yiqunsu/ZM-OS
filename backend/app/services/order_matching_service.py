"""Bounded existing master-data lookup; does not create entities or commit."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer, Formula, Product, ProductCategory
from app.schemas.agent.order_extraction import OrderExtraction
from app.services import agent_session_service as sessions
from app.services.order_extraction_normalizer import normalize_extraction


async def search_existing(db: AsyncSession, entity: str, query: str, limit: int = 10) -> list[dict]:
    mapping = {
        "customers": (Customer, Customer.company),
        "products": (Product, Product.name),
        "formulas": (Formula, Formula.name),
    }
    if entity not in mapping or not query.strip() or len(query) > 200 or not 1 <= limit <= 10:
        sessions.fail("INPUT_INVALID", "查询条件无效", 422)
    model, label = mapping[entity]
    rows = (
        await db.scalars(
            select(model)
            .where(label.icontains(query.strip(), autoescape=True))
            .order_by(label, model.id)
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": row.id,
            "label": getattr(row, label.key),
            **({"product_id": row.product_id} if entity == "formulas" else {}),
        }
        for row in rows
    ]


async def extracted_draft(db: AsyncSession, raw: OrderExtraction) -> dict:
    draft, _ = normalize_extraction(raw)
    for field, name, model, label in (
        ("customer_id", raw.customer_name, Customer, Customer.company),
        ("product_id", raw.product_description, Product, Product.name),
    ):
        if name:
            matches = (
                await db.scalars(
                    select(model.id).where(func.lower(func.trim(label)) == name.strip().lower()).limit(2)
                )
            ).all()
            if len(matches) == 1:
                draft[field] = matches[0]
    if raw.formula_raw and draft["product_id"]:
        matches = (
            await db.scalars(
                select(Formula.id)
                .where(
                    Formula.product_id == draft["product_id"],
                    func.lower(func.trim(Formula.name)) == raw.formula_raw.strip().lower(),
                )
                .limit(2)
            )
        ).all()
        if len(matches) == 1:
            draft["formula_mode"], draft["formula_id"] = "existing", matches[0]
    return draft


async def vision_catalog(db: AsyncSession) -> dict:
    """Small catalogs go to vision directly. Oversize fields remain manual, never silently shortlist."""
    import json

    catalog = {"customer_id": [], "product_id": [], "manual_fields": []}
    queries = {
        "customer_id": select(Customer.id, Customer.company.label("label")).order_by(
            Customer.company, Customer.id
        ),
        "product_id": select(Product.id, Product.name.label("label"), ProductCategory.name.label("category"))
        .join(ProductCategory)
        .order_by(Product.name, Product.id),
    }
    for field, query in queries.items():
        rows = [dict(row) for row in (await db.execute(query.limit(51))).mappings()]
        if len(rows) > 50 or len(json.dumps(rows, ensure_ascii=False).encode()) > 8000:
            catalog["manual_fields"].append(field)
        else:
            catalog[field] = rows
    return catalog


def visual_suggestions(raw, catalog: dict) -> tuple[dict, list[dict]]:
    """Accept only grounded, unambiguous choices. Diagnostics contain codes, never source text."""
    suggestions, diagnostics = {}, []
    for index, order in enumerate(raw.orders, 1):
        for field in ("customer_id", "product_id"):
            guess = getattr(order, field.replace("_id", "_match"))
            candidates = catalog[field]
            candidate = next((c for c in candidates if guess and c["id"] == guess.candidate_id), None)
            evidence = (
                "\n".join(filter(None, [raw.context_text, order.customer_name]))
                if field == "customer_id"
                else order.product_description or ""
            )
            reason = None
            if not guess:
                reason = "NO_CONFIDENT_MATCH"
            elif not candidate:
                reason = "INVALID_CANDIDATE"
            elif guess.confidence < 0.90 or guess.confidence - guess.runner_up_confidence < 0.15:
                reason = "LOW_CONFIDENCE"
            elif guess.evidence not in evidence:
                reason = "EVIDENCE_MISMATCH"
            elif (
                sum(
                    c["label"].strip().casefold() == candidate["label"].strip().casefold() for c in candidates
                )
                != 1
            ):
                reason = "AMBIGUOUS_NAME"
            if reason:
                diagnostics.append({"order_index": index, "field": field, "code": reason})
            else:
                suggestions.setdefault(index, {})[field] = {**guess.model_dump(), "label": candidate["label"]}
                diagnostics.append({"order_index": index, "field": field, "code": "ACCEPTED"})
    return suggestions, diagnostics


async def suggested_draft(db: AsyncSession, raw, suggestions: dict) -> tuple[dict, list[dict]]:
    draft = await extracted_draft(db, raw)
    issues = []
    for field, model, label in (
        ("customer_id", Customer, Customer.company),
        ("product_id", Product, Product.name),
    ):
        guess = suggestions.get(field)
        if draft[field] or not guess:
            continue
        # Recheck after the remote call. Deleted/renamed/ambiguous master data is not applied.
        ids = (
            await db.scalars(
                select(model.id)
                .where(func.lower(func.trim(label)) == guess["label"].strip().lower())
                .limit(2)
            )
        ).all()
        if ids != [guess["candidate_id"]]:
            continue
        draft[field] = guess["candidate_id"]
        if field == "product_id" and raw.product_description:
            description = f"截图产品原文：{raw.product_description}"
            draft["extra_notes"] = "；".join(filter(None, [description, draft["extra_notes"]]))[:2000]
        issues.append(
            {
                "field": field,
                "code": "ENTITY_INFERRED",
                "severity": "warning",
                "message": f"已根据截图匹配为「{guess['label']}」，请核对。依据：{guess['reason']}",
                "candidates": [{"id": guess["candidate_id"], "label": guess["label"]}],
                "confidence": guess["confidence"],
                "evidence": guess["evidence"],
            }
        )
    return draft, issues

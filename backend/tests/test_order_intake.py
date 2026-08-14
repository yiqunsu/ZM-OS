import base64

import pytest
from fastapi import HTTPException

from app.models import Customer, Formula, Product, ProductCategory
from app.services import order_intake_service


async def test_extract_order_draft_normalizes_and_matches_master_data(db_session, monkeypatch):
    category = ProductCategory(name="PE膜")
    customer = Customer(company="华兴包装", contact="张三")
    db_session.add_all([category, customer])
    await db_session.flush()
    product = Product(name="透明PE膜", category_id=category.id)
    db_session.add(product)
    await db_session.flush()
    formula = Formula(
        name="标准配方",
        product_id=product.id,
        spec_params={},
        materials="树脂 100%",
    )
    db_session.add(formula)
    await db_session.commit()

    async def fake_call_model(messages, model):
        assert messages[1]["content"] == "华兴要透明PE膜，50厚600宽，500公斤，标准配方"
        return {
            "customer_name": "华兴包装",
            "product_name": "透明PE膜",
            "formula_name": "标准配方",
            "spec_params": {"厚度": "50μm", "宽度": "600mm"},
            "quantity": "500",
            "unit": "KG",
            "ignored": "drop-me",
        }

    monkeypatch.setattr(order_intake_service, "_call_model", fake_call_model)
    draft = await order_intake_service.extract_order_draft(
        db_session,
        "华兴要透明PE膜，50厚600宽，500公斤，标准配方",
    )

    assert draft == {
        "customer_id": customer.id,
        "product_id": product.id,
        "spec_params": {"厚度": "50μm", "宽度": "600mm"},
        "quantity": 500.0,
        "unit": "kg",
        "formula_id": formula.id,
    }


def test_image_validation_rejects_invalid_format_and_oversize(monkeypatch):
    with pytest.raises(HTTPException, match="仅支持 JPG 或 PNG"):
        order_intake_service.validate_image_data_url("data:image/gif;base64,R0lGODlh")

    monkeypatch.setattr(order_intake_service.settings, "AGENT_IMAGE_MAX_BYTES", 4)
    encoded = base64.b64encode(b"\x89PNG\r\n\x1a\nmore").decode()
    with pytest.raises(HTTPException) as exc_info:
        order_intake_service.validate_image_data_url(f"data:image/png;base64,{encoded}")
    assert exc_info.value.status_code == 413


def test_image_validation_rejects_oversized_base64_before_decoding(monkeypatch):
    monkeypatch.setattr(order_intake_service.settings, "AGENT_IMAGE_MAX_BYTES", 3)
    oversized = "data:image/png;base64," + ("A" * 8)

    with pytest.raises(HTTPException) as exc_info:
        order_intake_service.validate_image_data_url(oversized)

    assert exc_info.value.status_code == 413


def test_image_validation_accepts_jpeg_and_png():
    jpeg = base64.b64encode(b"\xff\xd8\xfftest").decode()
    png = base64.b64encode(b"\x89PNG\r\n\x1a\ntest").decode()
    assert order_intake_service.validate_image_data_url(f"data:image/jpeg;base64,{jpeg}")
    assert order_intake_service.validate_image_data_url(f"data:image/png;base64,{png}")

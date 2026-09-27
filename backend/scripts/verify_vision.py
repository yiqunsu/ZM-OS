"""Paid, read-only model smoke check using committed synthetic image and real schema.

No database access or business orders are created. This does not test UI or Worker.
"""

import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError  # noqa: E402

from app.agent.model_transport import VisionError, call_vision_model  # noqa: E402
from app.agent.specialized import prompts  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.schemas.agent.entity_matching import extraction_schema  # noqa: E402


def verify_fields(result) -> bool:
    if len(result.orders) != 1:
        return False
    order = result.orders[0]
    if order.width.unit not in {"mm", "cm"} or order.thickness.unit not in {"μm", "丝"}:
        return False
    width = (order.width.value or 0) * (10 if order.width.unit == "cm" else 1)
    thickness = (order.thickness.value or 0) * (10 if order.thickness.unit == "丝" else 1)
    quantity = (order.quantity.value or 0) * {"kg": 1, "g": 0.001, "t": 1000}.get(order.quantity.unit, 0)
    return width == 705 and thickness == 80 and quantity == 1200


async def main() -> int:
    catalog = {"customer_id": [], "product_id": []}
    schema = extraction_schema(catalog)
    image = Path(__file__).resolve().parents[1] / "scripts/fixtures/order.png"
    messages = [
        {
            "role": "system",
            "content": prompts.EXTRACTION
            + "\nSchema:"
            + json.dumps(schema.model_json_schema(), ensure_ascii=False),
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": json.dumps({"catalog": catalog, "message": "请识别截图订单"})},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64," + base64.b64encode(image.read_bytes()).decode()
                    },
                },
            ],
        },
    ]
    try:
        response = await asyncio.wait_for(call_vision_model(messages, settings.LLM_VISION_MODEL), timeout=180)
        result = schema.model_validate(response)
        ok = verify_fields(result)
        print(json.dumps({"passed": ok, "check": "one_order_705mm_80um_1200kg"}, ensure_ascii=False))
        return 0 if ok else 1
    except VisionError as error:
        print(json.dumps({"passed": False, "code": error.code}))
    except ValidationError:
        print(json.dumps({"passed": False, "code": "SCHEMA_INVALID"}))
    except Exception as error:
        print(json.dumps({"passed": False, "error_type": type(error).__name__}))
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

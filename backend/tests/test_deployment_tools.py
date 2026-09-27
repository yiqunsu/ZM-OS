from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from scripts.deployment_report import differences
from scripts.verify_vision import verify_fields


@pytest.mark.parametrize(
    "options",
    [
        {"LLM_VISION_THINKING": "yes"},
        {"LLM_VISION_MAX_TOKENS": 0},
        {"LLM_REQUEST_TIMEOUT_SECONDS": 0},
    ],
)
def test_invalid_operational_settings_fail_early(options):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **options)


def test_configuration_drift_is_detected():
    assert differences(
        {"vision_model": "a", "vision_max_tokens": 8192}, {"vision_model": "b", "vision_max_tokens": 8192}
    ) == ["vision_model"]
    assert differences({"revision": "a"}, {}) == ["revision"]


def test_smoke_requires_count_units_and_values():
    order = SimpleNamespace(
        width=SimpleNamespace(value=70.5, unit="cm"),
        thickness=SimpleNamespace(value=8, unit="丝"),
        quantity=SimpleNamespace(value=1.2, unit="t"),
    )
    assert verify_fields(SimpleNamespace(orders=[order]))
    assert not verify_fields(SimpleNamespace(orders=[order, order]))
    order.width.unit = None
    assert not verify_fields(SimpleNamespace(orders=[order]))
    order.width.unit = "cm"
    order.quantity.value = 2
    assert not verify_fields(SimpleNamespace(orders=[order]))

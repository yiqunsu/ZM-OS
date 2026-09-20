"""Model suggestions are untrusted; candidates and acceptance are checked by the service."""

from typing import Annotated

from pydantic import ConfigDict, Field

from app.schemas.agent import AgentInput


class EntityGuess(AgentInput):
    model_config = ConfigDict(extra="forbid", strict=True)
    candidate_id: str = Field(min_length=1, max_length=128)
    confidence: Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
    runner_up_confidence: Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
    evidence: str = Field(min_length=2, max_length=300)
    reason: str = Field(min_length=1, max_length=300)


def extraction_schema(catalog: dict):
    """Bind this request's selectable IDs; the same schema is shown to and validated after the model."""
    from typing import Literal

    from pydantic import create_model

    from app.schemas.agent.order_extraction import OrderExtraction, ScreenshotExtraction

    fields = {}
    for field in ("customer_id", "product_id"):
        ids = tuple(row["id"] for row in catalog[field])
        choice = (
            create_model(field + "Choice", __base__=EntityGuess, candidate_id=(Literal[ids], ...))
            if ids
            else None
        )
        fields[field.replace("_id", "_match")] = (choice | None if choice else type(None), ...)
    order = create_model("CatalogOrder", __base__=OrderExtraction, **fields)
    return create_model(
        "CatalogScreenshot",
        __base__=ScreenshotExtraction,
        orders=(list[order], Field(min_length=1, max_length=20)),
    )

from uuid import UUID

from app.models.knowledge_base import KnowledgeCategory
from app.services.ai.knowledge_engine import KnowledgeSearchHit
from app.services.ai.prompt_engine import (
    BusinessTarget,
    CustomerProfile,
    CustomerSegment,
    DynamicPromptBuilder,
    WeatherContext,
)


def test_prompt_is_grounded_in_retrieved_knowledge() -> None:
    prompt = DynamicPromptBuilder().build(
        restaurant_context=[
            KnowledgeSearchHit(
                id=UUID(int=1),
                category=KnowledgeCategory.MENU,
                content_text="Nasi goreng tersedia.",
                similarity=0.98,
            )
        ],
        customer_profile=CustomerProfile(segment=CustomerSegment.VIP, summary="Frequent diner"),
        weather=WeatherContext(condition="Rain", temperature_celsius=26),
        business_target=BusinessTarget(objective="Increase repeat orders", success_metric="30-day repeat rate"),
    )

    assert "Nasi goreng tersedia." in prompt
    assert "VIP" in prompt
    assert "30-day repeat rate" in prompt

"""Dynamic, grounded prompt construction and resilient OpenAI invocation."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from openai import APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from app.services.ai.knowledge_engine import KnowledgeSearchHit


class CustomerSegment(StrEnum):
    VIP = "VIP"
    CHURN_RISK = "CHURN_RISK"


class CustomerProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    segment: CustomerSegment
    summary: str = Field(min_length=1, max_length=500)


class WeatherContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    condition: str = Field(min_length=1, max_length=100)
    temperature_celsius: float | None = None


class BusinessTarget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    objective: str = Field(min_length=1, max_length=500)
    success_metric: str = Field(min_length=1, max_length=200)


class OpenAIUnavailableError(RuntimeError):
    """A retryable dependency failure; callers should return a graceful fallback."""


class DynamicPromptBuilder:
    """Builds bounded, grounded instructions for restaurant AI experiences."""

    def build(
        self,
        *,
        restaurant_context: Sequence[KnowledgeSearchHit],
        customer_profile: CustomerProfile,
        weather: WeatherContext,
        business_target: BusinessTarget,
    ) -> str:
        knowledge = "\n\n".join(
            f"[{hit.category}] (similarity={hit.similarity:.3f})\n{hit.content_text}"
            for hit in restaurant_context
        ) or "No verified restaurant knowledge was retrieved."

        temperature = (
            f", {weather.temperature_celsius:.1f}°C"
            if weather.temperature_celsius is not None
            else ""
        )
        return f"""You are OrderlyFoods AI, an enterprise restaurant commerce assistant.

Use only the verified restaurant knowledge below for menu, opening-hours, refund, and SOP facts.
If a requested fact is absent, say that it cannot be verified; do not invent it. Never disclose
internal SOP content unless the user is authorized.

## Verified restaurant knowledge
{knowledge}

## Current customer
Segment: {customer_profile.segment}
Profile: {customer_profile.summary}

## Current weather
{weather.condition}{temperature}

## Business target
Objective: {business_target.objective}
Success metric: {business_target.success_metric}

Respond helpfully, concisely, and with recommendations aligned to the business target."""

    async def generate_with_openai(
        self,
        *,
        client: AsyncOpenAI,
        prompt: str,
        model: str,
        timeout_seconds: float = 20.0,
    ) -> str:
        """Send the final prompt and convert timeout/HTTP 503 into a retryable domain error."""
        try:
            response = await client.responses.create(
                model=model,
                input=prompt,
                timeout=timeout_seconds,
            )
            return response.output_text
        except APITimeoutError as exc:
            raise OpenAIUnavailableError("OpenAI request timed out; retry with backoff.") from exc
        except APIStatusError as exc:
            if exc.status_code == 503:
                raise OpenAIUnavailableError(
                    "OpenAI is temporarily unavailable (HTTP 503); retry with backoff."
                ) from exc
            raise

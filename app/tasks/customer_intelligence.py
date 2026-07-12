"""Celery pipeline that refreshes tenant-isolated customer AI profiles."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from openai import APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.celery import celery_app
from app.models.customer_intelligence import (
    CustomerAIProfile,
    CustomerSegment,
    Order,
    OrderItem,
    OrderStatus,
)
from app.services.ai.decision_engine import determine_next_best_action


class RetryableAIError(RuntimeError):
    """Transient OpenAI failure that Celery should retry with exponential backoff."""


class SegmentResponse(BaseModel):
    ai_customer_segment: CustomerSegment


@dataclass(frozen=True, slots=True)
class CustomerMetrics:
    aov_cents: int
    ltv_cents: int
    top_menu_items: list[str]


_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Initialize one reusable async connection pool per Celery worker process."""
    global _session_factory
    if _session_factory is None:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL must be configured for customer intelligence tasks")
        engine = create_async_engine(
            database_url, pool_pre_ping=True, pool_size=10, max_overflow=20
        )
        _session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return _session_factory


async def _calculate_customer_metrics(
    session: AsyncSession, *, tenant_id: UUID, customer_id: UUID
) -> CustomerMetrics:
    """Compute all monetary values in integer cents, never floating-point currency."""
    order_count, ltv_cents = (
        await session.execute(
            select(
                func.count(Order.id),
                func.coalesce(func.sum(Order.total_cents), 0),
            ).where(
                Order.tenant_id == tenant_id,
                Order.customer_id == customer_id,
                Order.status == OrderStatus.COMPLETED,
            )
        )
    ).one()
    total_orders = int(order_count)
    lifetime_value = int(ltv_cents)

    top_rows = (
        await session.execute(
            select(OrderItem.menu_item_name, func.sum(OrderItem.quantity).label("purchases"))
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                Order.tenant_id == tenant_id,
                Order.customer_id == customer_id,
                Order.status == OrderStatus.COMPLETED,
            )
            .group_by(OrderItem.menu_item_name)
            .order_by(func.sum(OrderItem.quantity).desc(), OrderItem.menu_item_name.asc())
            .limit(3)
        )
    ).all()

    return CustomerMetrics(
        aov_cents=lifetime_value // total_orders if total_orders else 0,
        ltv_cents=lifetime_value,
        top_menu_items=[str(menu_name) for menu_name, _ in top_rows],
    )


async def _classify_customer(metrics: CustomerMetrics) -> CustomerSegment:
    """Ask the model for a strictly constrained JSON classification."""
    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=20.0, max_retries=0)
    matrix: dict[str, Any] = {
        "aov_cents": metrics.aov_cents,
        "ltv_cents": metrics.ltv_cents,
        "top_menu_items": metrics.top_menu_items,
    }
    try:
        completion = await client.chat.completions.create(
            model=os.getenv("OPENAI_CUSTOMER_SEGMENT_MODEL", "gpt-4o-mini"),
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return valid JSON only, with exactly one key: ai_customer_segment. "
                        "Its value must be one of: VIP, Regular-Lovers, Discount-Seeker, Chun-Risk."
                    ),
                },
                {"role": "user", "content": json.dumps(matrix)},
            ],
        )
    except APITimeoutError as exc:
        raise RetryableAIError("OpenAI request timed out") from exc
    except APIStatusError as exc:
        if exc.status_code == 503:
            raise RetryableAIError("OpenAI returned HTTP 503") from exc
        raise

    content = completion.choices[0].message.content
    if not content:
        raise RetryableAIError("OpenAI returned an empty segment response")
    try:
        return SegmentResponse.model_validate_json(content).ai_customer_segment
    except ValidationError as exc:
        raise RetryableAIError("OpenAI returned an invalid customer segment") from exc


async def _sync_customer_ai_profile(customer_id: UUID, tenant_id: UUID) -> dict[str, Any]:
    session_factory = _get_session_factory()
    async with session_factory() as session:
        metrics = await _calculate_customer_metrics(
            session, tenant_id=tenant_id, customer_id=customer_id
        )

    segment = await _classify_customer(metrics)

    async with session_factory.begin() as session:
        profile = await session.scalar(
            select(CustomerAIProfile)
            .where(
                CustomerAIProfile.tenant_id == tenant_id,
                CustomerAIProfile.customer_id == customer_id,
            )
            .with_for_update()
        )
        if profile is None:
            profile = CustomerAIProfile(tenant_id=tenant_id, customer_id=customer_id, ai_customer_segment=segment)
            session.add(profile)

        profile.aov_cents = metrics.aov_cents
        profile.ltv_cents = metrics.ltv_cents
        profile.top_menu_items = metrics.top_menu_items
        profile.ai_customer_segment = segment
        action = await determine_next_best_action(
            session, tenant_id=tenant_id, customer_id=customer_id, segment=segment
        )

    return {
        "tenant_id": str(tenant_id),
        "customer_id": str(customer_id),
        "segment": segment.value,
        "next_best_action": action.action,
        "coupon_code": action.coupon_code,
    }


@celery_app.task(bind=True, name="customer_intelligence.sync_customer_ai_profile", max_retries=5)
def sync_customer_ai_profile(self: Any, customer_id: str, tenant_id: str) -> dict[str, Any]:
    """Refresh a profile after ``order.completed``; retry only transient AI outages."""
    try:
        return asyncio.run(_sync_customer_ai_profile(UUID(customer_id), UUID(tenant_id)))
    except RetryableAIError as exc:
        delay = min(60 * (2**self.request.retries), 900)
        raise self.retry(exc=exc, countdown=delay) from exc

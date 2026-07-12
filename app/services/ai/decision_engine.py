"""Tenant-scoped next-best-action rules for customer lifecycle engagement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer_intelligence import Coupon, CouponStatus, CustomerSegment


@dataclass(frozen=True, slots=True)
class NextBestAction:
    action: str
    coupon_code: str | None = None


async def determine_next_best_action(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    customer_id: UUID,
    segment: CustomerSegment,
) -> NextBestAction:
    """Apply deterministic, idempotent retention rules within one tenant boundary."""
    if segment is not CustomerSegment.CHURN_RISK:
        return NextBestAction(action="no_coupon_required")

    now = datetime.now(UTC)
    existing_coupon = await session.scalar(
        select(Coupon)
        .where(
            Coupon.tenant_id == tenant_id,
            Coupon.customer_id == customer_id,
            Coupon.status == CouponStatus.ACTIVE,
            Coupon.discount_basis_points == 1500,
            Coupon.expires_at > now,
        )
        .order_by(Coupon.created_at.desc())
        .limit(1)
    )
    if existing_coupon is not None:
        return NextBestAction(action="reuse_existing_15_percent_coupon", coupon_code=existing_coupon.code)

    coupon = Coupon(
        tenant_id=tenant_id,
        customer_id=customer_id,
        code=f"WINBACK15-{token_urlsafe(8).upper()}",
        discount_basis_points=1500,
        expires_at=now + timedelta(days=14),
    )
    session.add(coupon)
    await session.flush()
    return NextBestAction(action="issue_free_15_percent_coupon", coupon_code=coupon.code)

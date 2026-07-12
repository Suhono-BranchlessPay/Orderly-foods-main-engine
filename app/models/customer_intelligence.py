"""Persistence models for customer metrics, orders, and decision-engine coupons."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SQLAlchemyEnum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.knowledge_base import Base


class OrderStatus(StrEnum):
    COMPLETED = "completed"


class CustomerSegment(StrEnum):
    VIP = "VIP"
    REGULAR_LOVERS = "Regular-Lovers"
    DISCOUNT_SEEKER = "Discount-Seeker"
    CHURN_RISK = "Chun-Risk"


class CouponStatus(StrEnum):
    ACTIVE = "active"
    REDEEMED = "redeemed"
    EXPIRED = "expired"


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_tenant_customer_completed", "tenant_id", "customer_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False, index=True)
    customer_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False, index=True)
    status: Mapped[OrderStatus] = mapped_column(
        SQLAlchemyEnum(OrderStatus, name="order_status"), nullable=False, index=True
    )
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False)


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (Index("ix_order_items_order_menu", "order_id", "menu_item_name"),)

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    menu_item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)


class CustomerAIProfile(Base):
    __tablename__ = "customer_ai_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "customer_id", name="uq_customer_ai_profile_tenant_customer"),
        Index("ix_customer_ai_profiles_tenant_segment", "tenant_id", "ai_customer_segment"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False, index=True)
    customer_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False, index=True)
    aov_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ltv_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    top_menu_items: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    ai_customer_segment: Mapped[CustomerSegment] = mapped_column(
        SQLAlchemyEnum(CustomerSegment, name="customer_segment"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class Coupon(Base):
    __tablename__ = "coupons"
    __table_args__ = (
        UniqueConstraint("code", name="uq_coupons_code"),
        Index("ix_coupons_tenant_customer_status", "tenant_id", "customer_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False, index=True)
    customer_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    discount_basis_points: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[CouponStatus] = mapped_column(
        SQLAlchemyEnum(CouponStatus, name="coupon_status"), nullable=False, default=CouponStatus.ACTIVE
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

"""Tenant-isolated PostgreSQL knowledge records for the Enterprise Knowledge Engine."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Enum as SQLAlchemyEnum, Index, Text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative metadata root for OrderlyFoods persistence models."""


class KnowledgeCategory(StrEnum):
    MENU = "menu"
    OPERATING_HOURS = "operating_hours"
    REFUND_POLICY = "refund_policy"
    TRAINING_SOP = "training_sop"


class KnowledgeBase(Base):
    """A document chunk belonging to exactly one restaurant tenant."""

    __tablename__ = "knowledge_base"
    __table_args__ = (
        Index("ix_knowledge_base_tenant_category", "tenant_id", "category"),
        # PostgreSQL migration must run: CREATE EXTENSION IF NOT EXISTS vector.
        Index(
            "ix_knowledge_base_embedding_cosine",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"lists": 100},
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False, index=True
    )
    category: Mapped[KnowledgeCategory] = mapped_column(
        SQLAlchemyEnum(KnowledgeCategory, name="knowledge_category"), nullable=False, index=True
    )
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

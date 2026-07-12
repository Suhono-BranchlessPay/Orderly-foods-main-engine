"""Async, tenant-scoped semantic retrieval backed by pgvector."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_base import KnowledgeBase, KnowledgeCategory

EMBEDDING_DIMENSIONS = 1536


class InvalidEmbeddingError(ValueError):
    """Raised before a malformed vector can reach PostgreSQL."""


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Authenticated request context; it must be produced by tenancy middleware."""

    tenant_id: UUID


@dataclass(frozen=True, slots=True)
class KnowledgeSearchHit:
    id: UUID
    category: KnowledgeCategory
    content_text: str
    similarity: float


def _validate_embedding(query_embedding: Sequence[float]) -> list[float]:
    if len(query_embedding) != EMBEDDING_DIMENSIONS:
        raise InvalidEmbeddingError(
            f"Expected {EMBEDDING_DIMENSIONS} dimensions; received {len(query_embedding)}"
        )
    return [float(value) for value in query_embedding]


async def search_knowledge(
    session: AsyncSession,
    current: TenantContext,
    query_embedding: Sequence[float],
    *,
    limit: int = 5,
    category: KnowledgeCategory | None = None,
) -> list[KnowledgeSearchHit]:
    """Return relevant chunks for only ``current.tenant_id``.

    ``cosine_distance`` emits pgvector's cosine operator (`<=>`), which is accelerated by
    the table's ``vector_cosine_ops`` index. Tenant filtering is deliberately composed before
    the distance ordering, so another restaurant's knowledge can never become a candidate.
    """
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")

    vector = _validate_embedding(query_embedding)
    cosine_distance = KnowledgeBase.embedding.cosine_distance(vector).label("cosine_distance")

    statement: Select[tuple[KnowledgeBase, float]] = (
        select(KnowledgeBase, cosine_distance)
        .where(KnowledgeBase.tenant_id == current.tenant_id)
        .order_by(cosine_distance)
        .limit(limit)
    )
    if category is not None:
        statement = statement.where(KnowledgeBase.category == category)

    rows = (await session.execute(statement)).all()
    return [
        KnowledgeSearchHit(
            id=record.id,
            category=record.category,
            content_text=record.content_text,
            similarity=1 - float(distance),
        )
        for record, distance in rows
    ]

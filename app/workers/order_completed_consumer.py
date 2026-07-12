"""Bridge tenant-isolated order events to Celery customer intelligence jobs."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.core.events.event_bus import EventBus, TenantEvent, tenant_scoped_callback
from app.tasks.customer_intelligence import sync_customer_ai_profile


class OrderCompletedPayload(BaseModel):
    customer_id: UUID


def build_order_completed_callback(tenant_id: UUID):
    """Create a callback that can only receive this tenant's order.completed stream."""

    @tenant_scoped_callback(tenant_id)
    async def enqueue_customer_profile_sync(event: TenantEvent) -> None:
        payload = OrderCompletedPayload.model_validate(event.payload)
        sync_customer_ai_profile.delay(str(payload.customer_id), str(event.tenant_id))

    return enqueue_customer_profile_sync


async def consume_order_completed_events(event_bus: EventBus, tenant_id: UUID) -> None:
    await event_bus.subscribe_to_event("order.completed.v1", build_order_completed_callback(tenant_id))

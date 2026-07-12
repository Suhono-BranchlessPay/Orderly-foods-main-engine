from uuid import UUID

import pytest

from app.core.events.event_bus import EventBus, EventSubscriptionError, TenantEvent, tenant_scoped_callback


def test_event_contract_rejects_channel_injection() -> None:
    with pytest.raises(ValueError, match="cannot contain"):
        TenantEvent(tenant_id=UUID(int=1), event_type="order:created", payload={})


def test_event_contract_requires_namespaced_type() -> None:
    with pytest.raises(ValueError, match="namespaced"):
        TenantEvent(tenant_id=UUID(int=1), event_type="created", payload={})


@pytest.mark.asyncio
async def test_subscription_requires_tenant_bound_callback() -> None:
    bus = EventBus("redis://localhost:6379/0")

    async def callback(_: TenantEvent) -> None:
        pass

    with pytest.raises(EventSubscriptionError):
        await bus.subscribe_to_event("order.created.v1", callback)


def test_tenant_decorator_binds_exact_uuid() -> None:
    tenant_id = UUID(int=1)

    @tenant_scoped_callback(tenant_id)
    async def callback(_: TenantEvent) -> None:
        pass

    assert callback.__tenant_id__ == tenant_id

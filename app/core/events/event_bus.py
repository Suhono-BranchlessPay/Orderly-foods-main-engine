"""Redis Pub/Sub event transport with mandatory tenant boundaries."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator
from redis.asyncio import Redis
from redis.asyncio.client import PubSub

logger = logging.getLogger(__name__)


class TenantEvent(BaseModel):
    """Immutable, validated contract sent to Redis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    event_type: str = Field(min_length=3, max_length=128)
    payload: dict[str, JsonValue]
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("event_type")
    @classmethod
    def event_type_is_safe_for_channel(cls, value: str) -> str:
        """Prevent Redis channel injection and require a versioned domain name."""
        if ":" in value or any(character.isspace() for character in value):
            raise ValueError("event_type cannot contain ':' or whitespace")
        if "." not in value:
            raise ValueError("event_type must be a namespaced value, e.g. 'order.created.v1'")
        return value


EventCallback = Callable[[TenantEvent], Awaitable[None] | None]


class TenantScopedCallback(Protocol):
    __tenant_id__: UUID

    def __call__(self, event: TenantEvent) -> Awaitable[None] | None: ...


class EventSubscriptionError(ValueError):
    """Raised when a subscriber does not declare an exact tenant boundary."""


def tenant_scoped_callback(tenant_id: UUID) -> Callable[[EventCallback], EventCallback]:
    """Bind a callback to exactly one tenant before it may subscribe.

    The public subscription API intentionally has no optional tenant argument. Binding the
    callback first makes an unscoped (and therefore cross-tenant) subscription impossible.
    """

    def decorator(callback: EventCallback) -> EventCallback:
        setattr(callback, "__tenant_id__", tenant_id)
        return callback

    return decorator


class EventBus:
    """Asynchronous Redis Pub/Sub adapter with tenant-specific channels."""

    def __init__(self, redis_url: str, *, namespace: str = "orderly:v1:events") -> None:
        self._redis: Redis = Redis.from_url(redis_url, decode_responses=True)
        self._namespace = namespace.rstrip(":")

    def _channel_name(self, event_type: str, tenant_id: UUID) -> str:
        return f"{self._namespace}:{event_type}:{tenant_id}"

    async def publish_event(self, tenant_id: UUID, event_type: str, payload: dict[str, Any]) -> int:
        """Validate and publish an event only to the requesting tenant's channel."""
        event = TenantEvent(tenant_id=tenant_id, event_type=event_type, payload=payload)
        channel = self._channel_name(event.event_type, event.tenant_id)
        return await self._redis.publish(channel, event.model_dump_json())

    async def subscribe_to_event(self, event_type: str, callback_function: EventCallback) -> None:
        """Consume one tenant's event stream until the coroutine is cancelled.

        A callback must be decorated with :func:`tenant_scoped_callback`. This is a deliberate
        guard: a wildcard event subscription would expose other restaurants' messages.
        """
        tenant_id = getattr(callback_function, "__tenant_id__", None)
        if not isinstance(tenant_id, UUID):
            raise EventSubscriptionError(
                "callback_function must be decorated with @tenant_scoped_callback(tenant_id)"
            )

        # Reuse Pydantic validation for the event type before composing a Redis channel.
        validated_event_type = TenantEvent(
            tenant_id=tenant_id, event_type=event_type, payload={}
        ).event_type
        channel = self._channel_name(validated_event_type, tenant_id)
        pubsub: PubSub = self._redis.pubsub(ignore_subscribe_messages=True)

        try:
            await pubsub.subscribe(channel)
            while True:
                message = await pubsub.get_message(timeout=1.0)
                if message is None or message["type"] != "message":
                    continue

                event = TenantEvent.model_validate_json(message["data"])
                # Defense in depth: reject a malformed/badly routed broker message.
                if (
                    message["channel"] != channel
                    or event.tenant_id != tenant_id
                    or event.event_type != validated_event_type
                ):
                    logger.warning("Discarded event that violated its tenant channel boundary")
                    continue

                result = callback_function(event)
                if inspect.isawaitable(result):
                    await result
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    async def aclose(self) -> None:
        """Close the Redis connection when the worker shuts down."""
        await self._redis.aclose()

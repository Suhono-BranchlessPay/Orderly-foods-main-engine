# OrderlyFoods AI-OS 4.0

Fondasi FastAPI untuk AI Commerce OS jaringan restoran enterprise. Desain ini memisahkan batas domain, infrastruktur, dan transport agar tiap microservice dapat diekstrak tanpa mengubah kontrak domain.

## Struktur yang direkomendasikan

```text
app/
  api/                    # Router REST/WebSocket dan dependency request
  core/
    config.py              # Konfigurasi environment
    events/                # Kontrak event dan Redis Event Bus
    tenancy/               # TenantContext, resolusi tenant, dan guard akses
    security/              # JWT, RBAC, audit trail
  db/
    base.py                # SQLAlchemy metadata dan session async
    models/                # Model persistence per bounded context
    repositories/          # Query yang selalu tenant-scoped
  domains/
    orders/                # Entity, service, command, event domain
    menu/
    inventory/
    customers/
  agents/                  # Orchestrator, tools, memori, guardrail multi-agent AI
  workers/                 # Celery task; adapter yang mem-publish / consume event
  integrations/            # POS, payment, delivery marketplace adapters
  main.py
tests/
  unit/
  integration/
```

Untuk deployment microservices, pecah per bounded context (misalnya `orders-service`, `inventory-service`, dan `ai-agent-service`). Setiap service mempertahankan struktur internal yang sama, database/service credentials sendiri, dan hanya berkomunikasi melalui event contract versi-kan (`event_type`).

## Event Bus dan isolasi tenant

`EventBus` memakai channel Redis per event dan per tenant:

```text
orderly:v1:events:{event_type}:{tenant_id}
```

Tidak ada channel global. Subscriber **wajib** diikat pada satu tenant dengan decorator `tenant_scoped_callback`; `subscribe_to_event` menolak callback tanpa cakupan tenant. Selain pemisahan channel, envelope tervalidasi Pydantic dan tenant/event type diverifikasi lagi sebelum callback dijalankan.

## Instalasi

1. Buat virtual environment Python 3.11+ lalu pasang dependency: `pip install -e .`
2. Salin `.env.example` menjadi `.env` dan sesuaikan koneksi Redis/PostgreSQL.
3. Jalankan Redis, lalu FastAPI: `uvicorn app.main:app --reload`.

Contoh consumer:

```python
from uuid import UUID
from app.core.events.event_bus import EventBus, TenantEvent, tenant_scoped_callback

bus = EventBus("redis://localhost:6379/0")

@tenant_scoped_callback(UUID("11111111-1111-1111-1111-111111111111"))
async def on_order_created(event: TenantEvent) -> None:
    print(event.payload["order_id"])

await bus.subscribe_to_event("order.created.v1", on_order_created)
```

Publisher:

```python
await bus.publish_event(tenant_id, "order.created.v1", {"order_id": "ORD-1001"})
```

`subscribe_to_event` berjalan sebagai loop consumer hingga task dibatalkan. Jalankan pada worker process, bukan pada HTTP request handler.

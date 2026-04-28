---
# [Sprint A · Mini-prompt A5] Logging estructurado mínimo (4 flujos críticos)

**Fecha:** 2026-04-28 · **Estado:** ☑ verificado · ☐ cerrado

## Objetivo
Agregar logging estructurado mínimo con structlog en 4 flujos críticos: inventory_query, whatsapp_send, monday_op y handoff.

## Diagnóstico previo
- inbound_handler: punto de entrada en `handle`; ya había structlog y acceso a `conversation_id`/`lead_id` tras creación del lead.
- skills.query_inventory: ya tenía logs (`inventory_query_start/fallback/result`), sin `lead_id` ni `correlation_id`.
- monday_adapter: mutaciones principales en `upsert_lead` y `change_stage`; logs existentes, con `lead_id` parcial según operación.
- handoff_service: handoff en `take_control/release_control`; logs existentes sin `correlation_id` formal ni branch.
- grep structlog y get_logger confirmaron logger único por archivo (sin bound logger adicional).

## Cambios aplicados
| Archivo | Tipo | Resumen |
|---------|------|---------|
| core/services/skills.py | edit | Flujo `inventory_query` con eventos `started/ok/empty/error` y campos mínimos obligatorios |
| core/services/inbound_handler.py | edit | Flujo `whatsapp_send` alrededor de `send_text` con `started/ok/error` y `phone_masked` |
| adapters/crm/monday_adapter.py | edit | Flujo `monday_op` en `upsert_lead`/`change_stage` con `enqueued/ok/error` |
| core/services/handoff_service.py | edit | Flujo `handoff` en `take_control/release_control` con `started/ok/error` |

## Resolución de campos faltantes
- `skills.query_inventory`: no recibe contexto de conversación; `lead_id=None`, `correlation_id=None`.
- `monday_adapter.upsert_lead`: `lead_id/correlation_id` se intentan leer de `lead.attributes`; si no existen, `None`.
- `handoff_service`: `correlation_id` se resuelve con `session.id` como fallback de conversación; `branch=None` en este servicio.
- `whatsapp_send`: `correlation_id` desde `inbound_event.message_id`; `lead_id` no siempre disponible y se usa `None` cuando aplica.

## Evidencia (grep)
- `inventory_query_started` en `core/services/skills.py` ✅
- `whatsapp_send_ok|whatsapp_send_error` en `core/services/inbound_handler.py` ✅
- `monday_op_enqueued|monday_op_ok` en `adapters/crm/monday_adapter.py` ✅
- `handoff_started|handoff_ok` en `core/services/handoff_service.py` ✅

## CI
- `docker compose exec app pytest -v` -> **177 passed**
- `docker compose exec app ruff check . --fix` -> **All checks passed!**
- `docker compose exec app black .` -> **1 file reformatted, 172 unchanged**
- `docker compose exec app mypy core/` -> **Success: no issues found in 53 source files**

## Riesgos / pendientes
- Hay logs históricos en los mismos flujos con nomenclatura anterior; no se eliminaron para evitar refactor no solicitado.
- `branch` en `handoff_service` queda en `None` por diseño actual del servicio; sucursal se resuelve en `inbound_handler`.

## Siguiente paso sugerido
- A6: verificación E2E de observabilidad (dashboard/Sentry/log pipeline) para validar que los nuevos eventos alimentan métricas operativas.
---
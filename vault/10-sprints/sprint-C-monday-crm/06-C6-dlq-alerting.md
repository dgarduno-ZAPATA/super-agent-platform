---
# C6 — DLQ alerting con umbral configurable
**Sprint:** C (Monday CRM)
**Estado:** ? cerrado
**Fecha:** 2026-04-29

## Objetivo
Emitir alertas operativas cuando la cola DLQ del outbox CRM crece por encima de un umbral configurable en `brand.yaml`, sin romper el flujo del worker.

## Cambios implementados
- Se agregó `alerts` en `brand/brand.yaml` con:
  - `crm_dlq_threshold: 3`
  - `crm_pending_threshold: 50`
- Se creó `AlertsConfig` en `core/brand/schema.py` y se añadió `alerts` a `BrandConfig`.
- En `core/services/crm_worker.py`:
  - Se agregó `brand_config` opcional al constructor (fallback a `load_brand_config()`).
  - Se implementó `_check_dlq_alerts()` (best-effort, nunca relanza).
  - Se llama `_check_dlq_alerts()` al final de `process_batch()`.
  - Alerta por DLQ en warning log + captura en Sentry (si disponible).
  - Warning adicional por outbox pending alto.
- Se agregó test suite en `tests/unit/test_crm_dlq_alert.py`.

## Validación
- Cobertura de umbral alcanzado, bajo umbral, umbral exacto, pending threshold y tolerancia a fallos en check.
- Se mantuvo intacta la lógica principal de procesamiento/reintentos del batch.

## Notas
- `monday_adapter.py` e `inbound_handler.py` no fueron modificados.
- Este mini-prompt cierra Sprint C.
---

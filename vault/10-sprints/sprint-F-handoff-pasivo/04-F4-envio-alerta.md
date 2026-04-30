---
title: F4 Envio real de alerta y estados post-handoff
tags:
  - sprint
  - sprint-f
  - handoff
  - alertas
aliases:
  - F4 envio alerta
---

# F4 - Envio real de alerta + estados post-handoff

## Objetivo
- Enviar alerta enriquecida al asesor por WhatsApp real en flujo de handoff.
- Clasificar estado post-handoff para observabilidad (`responded`, `interested`, `active`, `stop`, `pending`).

## Diagnostico
- `HandoffService` no tenia `MessagingProvider` inyectado.
- No existia `handoff.notification_phone` en `brand.yaml` ni en `BrandConfig`.
- F3 solo generaba y loggeaba mensaje enriquecido; no lo enviaba.

## Cambios
- `core/services/handoff_service.py`
  - Constructor con `messaging_provider` y `brand_config` opcionales.
  - Nuevo metodo async `_send_handoff_alert()` best-effort (nunca lanza excepcion).
  - Nueva funcion pura `_classify_handoff_state(...)`.
  - `take_control()` ahora llama `await _send_handoff_alert(...)`.
- `core/brand/schema.py`
  - `HandoffConfig` con `notification_phone`.
  - `BrandConfig.handoff` agregado con `default_factory`.
- `brand/brand.yaml`
  - Nueva seccion:
    - `handoff.notification_phone: ""`
- `api/dependencies.py`
  - Inyeccion de `MessagingProvider` y `brand.brand` en `get_handoff_service`.
- `tests/unit/test_handoff_states.py`
  - 7 pruebas de clasificacion de estado.

## Validacion
- `pytest -v` verde.
- `ruff check . --fix` verde.
- `black .` sin cambios pendientes.
- `mypy core/` verde.

## Riesgos y deudas
- Si no hay `branch_phone`/`sucursal_phone` en contexto y `notification_phone` vacio, solo se loggea warning (best-effort).
- Aun falta verificar en entorno real que el telefono de sucursal llegue siempre en contexto para cada marca.

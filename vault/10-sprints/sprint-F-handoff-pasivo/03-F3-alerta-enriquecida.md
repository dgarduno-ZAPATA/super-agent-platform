---
title: F3 Alerta enriquecida para asesor
tags:
  - sprint
  - sprint-f
  - handoff
  - alerta
aliases:
  - F3 advisor alert
---

# F3 - Alerta enriquecida al asesor

## Objetivo
- Construir mensaje enriquecido para asesor con `wa.me`, urgencia y contexto minimo del lead.
- Mantener funcion pura para componer texto y facilitar pruebas unitarias.

## Diagnostico y decision
- `core/services/handoff_service.py` no enviaba alerta al asesor; solo cambiaba estado (`handoff_active`/`idle`) y registraba evento de sistema.
- `brand/brand.yaml` no trae template dedicado para alerta al asesor (solo mensajes de handoff al cliente).
- Para no romper firmas publicas, se integro log estructurado enriquecido dentro de `take_control` usando datos best-effort desde `session.context`.
- Deuda tecnica F3-b/F4: mover origen de datos a `LeadProfile` persistente y conectar envio real por proveedor de mensajeria.

## Cambios implementados
- `core/services/handoff_service.py`
  - Nueva funcion pura `_build_advisor_alert(...)`.
  - Nuevos helpers `_urgency_level(...)` y `_maybe_float(...)`.
  - Integracion en `take_control` mediante `_log_handoff_alert_enriched(...)`.
  - Nuevo log `handoff_alert_enriched` con `urgency`, flags de contexto y `message`.
- `tests/unit/test_advisor_alert.py`
  - 10 pruebas unitarias para nombre, `wa.me`, urgencia, ciudad y normalizacion de telefono.

## Validacion
- `pytest tests/unit/test_advisor_alert.py -v` -> 10 passed.
- `pytest -v` -> 330 passed, 1 warning.
- `ruff check . --fix` -> All checks passed.
- `black .` -> 216 files left unchanged.
- `mypy core/` -> Success (66 source files).

## Riesgos para F4
- El enriquecimiento actual depende de `session.context`; si faltan atributos, la alerta sale parcial.
- No hay envio directo al asesor desde este servicio aun, solo log estructurado listo para consumo.

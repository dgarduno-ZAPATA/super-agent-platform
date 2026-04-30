---
title: F2 Deteccion from_me humano y silencio 60 min
tags:
  - sprint
  - sprint-f
  - handoff
  - silence
aliases:
  - F2 human silence
---

# F2 - Deteccion from_me humano -> silencio 60 min

## Objetivo
- Cuando llega `from_me=True`, distinguir bot vs asesor humano usando `outbound_cache`.
- Si es asesor humano, silenciar el bot por 60 minutos para ese telefono.

## Diagnostico y decision
- `Session` no tiene `silenced_until` ni `human_control_until`.
- Ya existe silencio persistente por repositorio (`SilencedUserRepository`) para opt-out.
- Para F2 se implemento **Opcion B**: cache de modulo por telefono con TTL 60 min.
- Deuda tecnica: mover este silencio temporal a estado persistente en sesion (Sprint F4).

## Cambios implementados
- `core/services/inbound_handler.py`
  - Nueva funcion pura `_is_human_advisor_message(...)`.
  - Nuevo cache de modulo `_advisor_silence` y guard por TTL.
  - Deteccion temprana de `from_me=True`:
    - si `message_id` esta en `outbound_cache` -> `own_message_skipped`.
    - si NO esta -> `advisor_message` + `_apply_advisor_silence(...)`.
  - Nuevo metodo `_apply_advisor_silence(...)` con duracion fija de 60 min.
- `tests/unit/test_human_silence.py`
  - 5 pruebas unitarias para la funcion pura.

## Validacion
- `pytest tests/unit/test_human_silence.py -v` -> 5 passed.
- `pytest -v` -> 320 passed.
- `ruff check . --fix` -> OK.
- `black .` -> unchanged.
- `mypy core/` -> Success (66 files).

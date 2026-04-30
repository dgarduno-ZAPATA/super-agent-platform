---
title: F1 Cache de message_id propios del bot
tags:
  - sprint
  - sprint-f
  - handoff
  - evolution
aliases:
  - F1 outbound cache
---

# F1 - Cache de message_id propios del bot

## Objetivo
- Propagar `from_me` desde webhook Evolution hasta `InboundEvent`.
- Cachear `message_id` de envios exitosos del bot para distinguirlos de mensajes humanos.

## Cambios implementados
- `adapters/messaging/evolution/payloads.py`
  - `EvolutionMessageKey` ahora modela `from_me` con alias `fromMe`.
- `core/domain/messaging.py`
  - `InboundEvent` incorpora campo `from_me: bool = False`.
- `adapters/messaging/evolution/outbound_cache.py`
  - Nuevo cache singleton `outbound_cache` con TTL y limite maximo.
- `adapters/messaging/evolution/adapter.py`
  - `parse_inbound_event` propaga `from_me` a `InboundEvent` y `raw_metadata`.
  - `_send_message` cachea `receipt.message_id` en envios exitosos y loguea `outbound_message_cached`.
- Tests nuevos:
  - `tests/unit/test_outbound_cache.py` (5 tests)
  - `tests/unit/test_inbound_from_me.py` (2 tests)

## Validacion
- `pytest -v` -> 315 passed.
- `ruff check . --fix` -> OK.
- `black .` -> unchanged.
- `mypy core/` -> Success (66 files).

## Riesgos para F2
- Cache en memoria por proceso: en escenarios multi-instancia no comparte estado entre instancias.
- TTL de 2 horas y podas por tamano deben monitorearse en trafico alto para ajustar cardinalidad.

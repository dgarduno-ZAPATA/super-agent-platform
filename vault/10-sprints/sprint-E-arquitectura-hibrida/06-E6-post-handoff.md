---
# [Sprint E · Mini-prompt E6] Comportamiento post-handoff

**Fecha:** 2026-04-28 · **Estado:** ? verificado · ? cerrado

## Objetivo
Definir comportamiento del bot en `handoff_pending` y `handoff_active` para evitar calificación e inventario mientras el humano toma control.

## Diagnóstico previo
- `ConversationAgent.respond()` no tenía bloque especial para `handoff_pending`/`handoff_active`.
- `InboundMessageHandler` ya bloquea `handoff_active` al inicio (`status=handoff_active`), pero no bloquea explícitamente `handoff_pending`.
- En `fsm.yaml`, `handoff_pending` y `handoff_active` no aceptan transición por `user_message`; solo comandos/agente/timeout/opt_out.
- Aun así, si entra `user_message` en `handoff_pending` y no hay transición, el flujo puede seguir a `conversation_agent.respond()` con estado sin cambio.

## Opción elegida
- **Opción A (guard en `conversation_agent.respond()`)**.
- Justificación: el alcance de E6 restringe cambios a `conversation_agent.py`/tests; además `respond()` sí puede ejecutarse con estado `handoff_pending`.

## Cambios aplicados
| Archivo | Tipo | Resumen |
|---------|------|---------|
| core/services/conversation_agent.py | edit | `HANDOFF_STATES`, `HANDOFF_MSG`, `should_send_handoff_message()` y salida temprana en `respond()` sin llamar LLM en handoff |
| tests/unit/test_post_handoff.py | add | 5 tests para la lógica de decisión post-handoff |

## Regla implementada
- Mensaje exacto hardcodeado (con TODO para mover a brand):
  `"Ya le avisé a un asesor, en breve te atiende."`
- En `handoff_pending`/`handoff_active`:
  - si aún no se envió ese mensaje en los últimos 2 bot-messages ? se envía una vez;
  - si ya se envió ? silencio;
  - en ambos casos se retorna sin llamar al LLM.

## Tests
- test_handoff_pending_first_message ? PASS
- test_handoff_active_first_message ? PASS
- test_handoff_already_sent_silence ? PASS
- test_non_handoff_state_not_affected ? PASS
- test_handoff_other_bot_messages_not_silence ? PASS

## CI
- `docker compose exec app pytest tests/unit/test_post_handoff.py -v` ? 5 passed
- `docker compose exec app pytest -v` ? 235 passed
- `docker compose exec app ruff check . --fix` ? All checks passed
- `docker compose exec app black .` ? 186 files left unchanged
- `docker compose exec app mypy core/` ? Success (60 source files)

## Riesgos / pendientes
- `handoff_active` ya se silencia desde inbound_handler; la nueva lógica en agent queda como red de seguridad.
- El texto está hardcodeado por requisito; mover a config de marca en Sprint B.

## Siguiente paso sugerido
- E7: gestión de fricción (confusión repetida ? escalar) reutilizando señales de anti-repetición y estado FSM.
---

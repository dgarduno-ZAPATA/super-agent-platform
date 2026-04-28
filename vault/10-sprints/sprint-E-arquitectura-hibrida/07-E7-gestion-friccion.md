---
# [Sprint E · Mini-prompt E7] Gestión de fricción

**Fecha:** 2026-04-28 · **Estado:** ? verificado · ? cerrado

## Objetivo
Detectar fricción conversacional (atasco/confusión repetida) y escalar con mensaje de reconocimiento + señal de handoff cuando sea posible.

## Diagnóstico previo
- `ConversationAgent` no tenía detector de fricción ni rama de escalación previa al envío.
- `ConversationAgent` sí conoce `session.current_state` y recibe historial (`conversation_history`) para derivar contexto reciente.
- El flujo de handoff real hoy se orquesta en `InboundMessageHandler` (clasificación + `_route_handoff_to_branch` + `_activate_handoff_session`).
- Disparar ese handoff directamente desde `ConversationAgent` introduce acoplamiento/dep circular de servicios (no viable en este alcance).

## Implementación
| Archivo | Tipo | Resumen |
|---------|------|---------|
| core/services/friction_detector.py | add | `FRICTION_KEYWORDS`, señales de estancamiento/keywords, `detect_friction()` y logs estructurados |
| core/services/conversation_agent.py | edit | Integración de `detect_friction` antes de enviar respuesta; mensaje de escalación y log `friction_escalation_triggered` |
| tests/unit/test_friction_detector.py | add | 8 tests unitarios puros para keyword/stale-state/thresholds |

## Mecanismo de escalación en E7
- Si hay fricción, el bot reemplaza la respuesta por:
  `Entiendo que no he sido de ayuda. Déjame conectarte con un asesor ahora mismo.`
- Se registra:
  `friction_escalation_triggered` con `handoff_triggered=False`.
- **Limitación documentada:** no se dispara handoff automático desde `ConversationAgent` para evitar dependencia circular con `InboundMessageHandler`.

## Construcción de contexto para fricción
- `recent_client_messages`: se derivan de `messages` (rol `user`) y se excluye el mensaje actual si ya aparece al final.
- `recent_states`: se leen desde `history[*].payload["state"]` cuando existe.
- Si no hay estados históricos, se usa aproximación segura con estado actual repetido por número de turnos observados (sin forzar umbral artificial).

## Tests (friction detector)
- test_friction_keyword_detected ? PASS
- test_no_friction_keyword ? PASS
- test_stale_state_triggers_friction ? PASS
- test_stale_state_below_threshold_no_friction ? PASS
- test_different_states_no_stale_friction ? PASS
- test_keyword_threshold_triggers_friction ? PASS
- test_single_keyword_no_friction ? PASS
- test_empty_history_no_friction ? PASS

## CI
- `docker compose exec app pytest tests/unit/test_friction_detector.py -v` ? 8 passed
- `docker compose exec app pytest -v` ? 243 passed
- `docker compose exec app ruff check . --fix` ? 1 fix aplicado, luego sin errores
- `docker compose exec app black .` ? 188 files left unchanged
- `docker compose exec app mypy core/` ? Success (61 source files)

## Riesgos / deudas técnicas post-Sprint E
- Handoff automático por fricción pendiente de integración explícita en capa de orquestación/FSM para evitar acoplamiento de `ConversationAgent`.
- `FRICTION_ESCALATION_MSG` y `HANDOFF_MSG` siguen hardcodeados (deuda Sprint B: mover a `brand/`).
- Detector de keywords puede requerir calibración por marca para reducir falsos positivos/negativos.

## Cierre de Sprint E
- Este mini-prompt E7 queda cerrado y completa el Sprint E.
---

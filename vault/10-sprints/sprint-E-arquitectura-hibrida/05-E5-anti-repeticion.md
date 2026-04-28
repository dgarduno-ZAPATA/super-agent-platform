---
# [Sprint E · Mini-prompt E5] Anti-repetición Jaccard

**Fecha:** 2026-04-28 · **Estado:** ? verificado · ? cerrado

## Objetivo
Agregar guardia anti-repetición por similitud Jaccard para evitar que el bot envíe respuestas demasiado similares de forma consecutiva.

## Diagnóstico previo
- El texto final se arma en `response_text` dentro de `ConversationAgent.respond()` después de `_run_tool_calling_loop` usando `llm_response.content`.
- En ese punto sí hay historial disponible (`history`) y también mensajes formateados (`messages`) desde donde se pueden extraer respuestas previas del bot.
- No existía regeneración anti-repetición antes de este cambio.
- `LLMResponse` expone el texto generado en `content`.

## Adaptación al flujo real
- Se usó `llm_response.content` como entrada para `_compress_response_text(...)` y luego se evalúa repetición sobre `response_text` (texto real a enviar).
- `previous_bot_texts` se construyó desde `messages` filtrando `role == "assistant"`.
- Se implementó regeneración en `respond()` con `MAX_REGEN_ATTEMPTS = 2`.
- Si supera intentos, se conserva la última respuesta y se loggea `repetition_max_attempts_reached`.

## Cambios aplicados
| Archivo | Tipo | Resumen |
|---------|------|---------|
| core/services/repetition_guard.py | add | Tokenización, Jaccard, `is_repetition`, logs estructurados (`repetition_detected`) |
| core/services/conversation_agent.py | edit | Integración de `is_repetition` + loop de regeneración antes de enviar mensaje |
| tests/unit/test_repetition_guard.py | add | 10 tests unitarios para tokenización/similitud/repetición |

## Tests (repetition_guard)
- test_jaccard_identical ? PASS
- test_jaccard_no_overlap ? PASS
- test_jaccard_partial ? PASS
- test_jaccard_empty_string ? PASS
- test_repetition_detected_above_threshold ? PASS
- test_no_repetition_below_threshold ? PASS
- test_no_repetition_empty_history ? PASS
- test_no_repetition_empty_candidate ? PASS
- test_lookback_only_last_3 ? PASS
- test_custom_threshold ? PASS

## CI
- `docker compose exec app pytest tests/unit/test_repetition_guard.py -v` ? 10 passed
- `docker compose exec app pytest -v` ? 230 passed
- `docker compose exec app ruff check . --fix` ? All checks passed
- `docker compose exec app black .` ? 185 files left unchanged
- `docker compose exec app mypy core/` ? Success (60 source files)

## Riesgos / pendientes
- Con temperatura baja y mismo contexto, la regeneración puede producir respuestas aún similares; mitigar en E6 con estrategia post-handoff/filtros de contexto.
- Jaccard por tokens no detecta bien repeticiones semánticas con vocabulario distinto; posible mejora futura con similitud semántica.

## Siguiente paso sugerido
- E6: comportamiento post-handoff para evitar recalificación y reducir loops de respuesta repetitiva tras intervención humana.
---

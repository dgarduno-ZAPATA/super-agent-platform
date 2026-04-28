---
# [Sprint E · Mini-prompt E3] Integrar SlotExtractor + restringir tool-calling

**Fecha:** 2026-04-28 · **Estado:** ? verificado (CAMBIO 1) · ? pendiente (CAMBIO 2)

## Objetivo
Integrar `SlotExtractor` al pipeline inbound manteniendo compatibilidad legacy, y preparar restricción de tool-calling por `allowed_tools`.

## Diagnóstico previo
- Extracción ad-hoc de slots estaba en `InboundMessageHandler._update_lead_profile_from_inbound`.
- Guards FSM leen `name` y `phone` en contexto plano (`has_name_guard`, `has_phone_number_guard`).
- `ConversationAgent._run_tool_calling_loop()` usa siempre `self._skill_registry.get_tool_schemas()` sin filtrado.
- No existe mecanismo activo de filtrado de tools por estado/contexto.

## Cambios aplicados
| Archivo | Tipo | Resumen |
|---------|------|---------|
| core/services/slot_extractor.py | edit | Se agregó `slots_to_legacy_dict(slots: LeadSlots)` para mapear a claves legacy (`vehiculo_interes`, `ciudad`, etc.) |
| core/services/inbound_handler.py | edit | Se reemplazó extracción ad-hoc principal por `SlotExtractor` + merge legacy + log `slot_extraction_done` |
| tests/unit/test_slot_extractor.py | edit | Se agregaron 3 tests para `slots_to_legacy_dict` |

## Split aplicado por protocolo
- `core/services/inbound_handler.py` cambió 54 líneas (`git diff --numstat`), superando el umbral de 30 líneas definido en E3.
- Se ejecutó solo CAMBIO 1 y se dejó CAMBIO 2 pendiente para siguiente instrucción.

## Tests / CI
- `docker compose exec app pytest tests/unit/test_slot_extractor.py -v` ? 27 passed
- `docker compose exec app pytest -v` ? 204 passed
- `docker compose exec app ruff check . --fix` ? All checks passed
- `docker compose exec app black .` ? 179 files left unchanged
- `docker compose exec app mypy core/` ? Success (58 source files)

## Riesgos / pendientes
- Pendiente CAMBIO 2: restricción de tools por `allowed_tools` en `conversation_agent.py`.
- Mientras CAMBIO 2 no se integre, el LLM sigue recibiendo el catálogo completo de tools.

## Siguiente paso sugerido
- E3-b: implementar CAMBIO 2 en `conversation_agent.py` + tests unitarios de filtrado (`allowed_tools=None|[]|[query_inventory]`) sin tocar lógica de negocio.
---
## E3-b — Tool calling filter
- Se actualizó `core/services/conversation_agent.py` para soportar filtrado opcional por `allowed_tools` dentro de `_run_tool_calling_loop`.
- `respond()` ahora invoca `_run_tool_calling_loop(..., allowed_tools=None)` para mantener comportamiento de producción sin cambios.
- Se agregó log estructurado `tool_calling_filtered` cuando `allowed_tools` es distinto de `None`.
- Se agregó `tests/unit/test_conversation_agent_tool_filter.py` con 3 pruebas de filtrado (`single`, `empty`, `none`).

### CI E3-b
- `docker compose exec app pytest -v` ? 207 passed
- `docker compose exec app ruff check . --fix` ? All checks passed
- `docker compose exec app black .` ? 180 files left unchanged
- `docker compose exec app mypy core/` ? Success (58 source files)

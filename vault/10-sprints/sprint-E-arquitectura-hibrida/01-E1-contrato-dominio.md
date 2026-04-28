---
# [Sprint E · Mini-prompt E1] Contrato de dominio (IntentRegistry, ActionRegistry, SlotSchema)

**Fecha:** 2026-04-28 · **Estado:** ☑ verificado · ☐ cerrado

## Objetivo
Definir el contrato de dominio para arquitectura híbrida sin modificar lógica de negocio existente.

## Prompt enviado a Dev-AI
- Crear solo 4 archivos nuevos en `core/domain/`
- Tipos con dataclasses/enums
- Agregar `allowed_tools` a `AgentAction`
- Sin tocar archivos existentes

## Diagnóstico previo aprobado
- `conversation_agent` usa tool-calling y permite decisiones de tools por LLM
- `orchestrator` clasifica intención y produce `fsm_event`
- FSM evalúa guards por contexto `dict` sin slots tipados
- Dominio no tenía modelos explícitos de Intent/Action/Slots/AgentContext

## Cambios aplicados
| Archivo | Tipo | Resumen |
|---------|------|---------|
| core/domain/intent.py | add | `IntentType` + `Intent` |
| core/domain/slots.py | add | `LeadSlots` + `SlotExtractionResult` con regla null estricta |
| core/domain/action.py | add | `ActionType` + `AgentAction` con `allowed_tools` |
| core/domain/agent_context.py | add | `AgentContext` como objeto único de entrada al LLM |

## Criterios / validación
- grep imports prohibidos (`from adapters|from api|from core.services`) en los 4 archivos nuevos: sin resultados
- pytest: 177 passed
- ruff: All checks passed
- black: 177 files left unchanged
- mypy core/: Success (57 source files)

## Decisiones de diseño
- Se tipó `context` como `dict[str, object]` en `AgentAction` para cumplir mypy strict.
- Se tipó `inventory_results` y `conversation_history` como `list[dict[str, object]]` en `AgentContext`.
- No se añadieron campos extra fuera de lo solicitado.

## Riesgos detectados (E2/E3)
- E2 debe mapear extracción determinística a `LeadSlots` sin romper `lead.attributes` legacy.
- E3 debe acotar tool-calling real a `allowed_tools` para evitar libertad del LLM.
- Se requiere puente entre `MessageClassification` actual y `Intent` nuevo.

## Siguiente paso sugerido
- E2: implementar extractor determinístico y testear regla null estricta (sin inferencias).
---
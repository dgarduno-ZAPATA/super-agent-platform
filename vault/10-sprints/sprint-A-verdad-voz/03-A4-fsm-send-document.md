---
# [Sprint A · Mini-prompt A4] Desactivar send_document en FSM

**Fecha:** 2026-04-28 · **Estado:** ☑ verificado · ☐ cerrado

## Objetivo
Desactivar el envío de documentos PDF en el flujo FSM de Sprint A, manteniendo el flujo conversacional y sin introducir lógica nueva de envío.

## Prompt enviado a Dev-AI
- Diagnóstico de `brand/fsm.yaml` y `core/fsm/actions.py`
- Greps globales de `send_document` y `example.com`
- Eliminar `send_document` de acciones FSM activas
- Ejecutar CI completa y reportar resultados

## Diagnóstico reportado por Dev-AI
- `send_document` estaba activo en `brand/fsm.yaml` dentro de `document_delivery.on_enter`.
- Transición de activación: `catalog_navigation` -> `document_delivery` con `event: user_message` + `guard: user_requested_document`.
- Existe estado `document_delivery`.
- En `core/fsm/actions.py` existe `send_document_action` con manejo de errores (`try/except`) y fallback de texto.
- `grep -rn "example.com" brand/` no arrojó resultados.

## Caso detectado
- Caso 1: `send_document` activo en FSM.
- Caso 2: no aplicó (ya existe manejo de error en `actions.py`).

## Cambios aplicados
| Archivo | Tipo | Resumen |
|---------|------|---------|
| brand/fsm.yaml | edit | Eliminado `send_document` de `document_delivery.on_enter` y agregada nota inline `DISABLED` para Sprint A |

## Evidencia (grep)
- `grep -n "send_document" brand/fsm.yaml` -> sin resultados
- `grep -n "DISABLED: PDFs fuera de scope Sprint A" brand/fsm.yaml` -> línea 204

## Tests
- pytest: 177 passed in 92.99s (0:01:32)
- ruff: All checks passed!
- black: All done! 173 files left unchanged.
- mypy: Success: no issues found in 53 source files (nota: unused section module=['pytest.*'])

## Riesgos / pendientes
- El estado `document_delivery` y su transición siguen existiendo; queda como estado de paso sin envío de PDF durante Sprint A.
- Persisten referencias a `send_document` fuera de FSM (skills/messaging ports/adapters), fuera del alcance de este mini-prompt.

## Siguiente paso sugerido
- A5/A6: validación E2E de rutas `user_requested_document` para confirmar que no rompe experiencia y que el bot continúa con resumen de especificaciones en texto.
---
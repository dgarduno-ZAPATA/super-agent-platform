# [Sprint C · Mini-prompt C5] Resumen IA por evento + nota en Monday

**Fecha:** 2026-04-28 · **Estado:** ☑ verificado · ☐ cerrado

## Objetivo
Generar resúmenes breves con LLM en eventos clave y publicarlos como update en Monday para dar contexto inmediato al asesor.

## Prompt enviado a Dev-AI
- Crear `ConversationSummaryService` con fallback seguro
- Cambiar `MondayCRMAdapter.add_note` a mutation `create_update`
- Mantener integración por outbox (sin tocar inbound_handler)
- Agregar tests unitarios de summary y add_note

## Diagnóstico reportado por Dev-AI
- `CRMProvider` ya exponía `add_note(...)` y usa patrón `Protocol`.
- `MondayCRMAdapter.add_note` existía, pero escribía en columna `Notas` con `change_column_value` y relanzaba excepción.
- `CRMSyncWorker` ya procesa operación `add_note` en `_dispatch_operation`, sin cambios estructurales.
- No existía servicio `ConversationSummaryService`.

## Cambios aplicados
| Archivo | Tipo | Resumen |
|---------|------|---------|
| core/services/conversation_summary.py | add | Servicio nuevo para resumen IA (máx. 6 turnos), fallback seguro, logs `conversation_summary_generated/failed` |
| adapters/crm/monday_adapter.py | edit | `add_note` ahora usa `create_update`; best-effort (log warning en fallo, no relanza) |
| tests/unit/test_conversation_summary.py | add | 6 tests (historial, fallback, fallo LLM, respuesta vacía, fallback minimal/full) |
| tests/unit/test_monday_add_note.py | add | 2 tests (éxito create_update, fallo sin relanzar) |
| vault/10-sprints/sprint-C-monday-crm/05-C5-resumen-ia.md | add | Trazabilidad de C5 |

## Integración (outbox vs llamada directa)
- **Se mantuvo vía outbox**.
- Justificación: `crm_worker.py` ya soporta operación `add_note` y llama `crm_provider.add_note(...)`.
- No fue necesario tocar `crm_worker.py` ni `inbound_handler.py`.

## Tests / CI
- tests nuevos ejecutados:
  - `tests/unit/test_conversation_summary.py` -> 6 passed
  - `tests/unit/test_monday_add_note.py` -> 2 passed
- CI completo:
  - `pytest -v` -> 287 passed
  - `ruff check . --fix` -> All checks passed
  - `black .` -> 1 archivo reformateado (`test_conversation_summary.py`)
  - `mypy core/` -> Success (64 source files)

## Riesgos / pendientes
- `ConversationSummaryService` quedó creado pero aún no hay disparador automático de eventos clave en este mini-prompt; la publicación depende de encolar `add_note` desde los eventos en C6.
- `SUMMARY_MAX_TOKENS` se conserva como constante de control de costo (150), pero el puerto LLM actual no acepta `max_tokens` explícito; se controla por prompt y tamaño de contexto.

## Comandos para reproducir
```bash
docker compose exec app pytest tests/unit/test_conversation_summary.py tests/unit/test_monday_add_note.py -v
docker compose exec app pytest -v
docker compose exec app ruff check . --fix
docker compose exec app black .
docker compose exec app mypy core/
```

## Siguiente paso sugerido
- C6: DLQ alerting + wiring de triggers (`handoff_requested`, `stage_change`, `friction_escalation`) para encolar operación `add_note` con resumen generado.

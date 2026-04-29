# [Sprint C · Mini-prompt C2] Dedup por telefono antes de crear lead

**Fecha:** 2026-04-28 · **Estado:** ☑ verificado · ☐ cerrado

## Objetivo
Evitar duplicados en Monday buscando primero por la llave tecnica `Phone Dedupe` (`text_mm2kjsap`) antes de crear un item nuevo.

## Prompt enviado a Dev-AI
- Diagnosticar decision actual create/update en `MondayCRMAdapter`
- Implementar dedup por telefono antes de `create_item`
- Mantener firma publica de `upsert_lead`
- Agregar pruebas unitarias de dedup y normalizacion

## Diagnostico reportado por Dev-AI
- `upsert_lead()` antes de este cambio buscaba siempre por telefono via `_find_item_by_phone(lead.phone)` y luego:
  - si encontraba item -> `change_multiple_column_values` (update)
  - si no -> `create_item`
- No priorizaba `lead.external_id` ni `lead.attributes["monday_id"]` antes de buscar por telefono.
- `_find_item_by_phone` consultaba la columna visible de telefono (`text_mm2k3epp`), no la llave tecnica `text_mm2kjsap`.
- `Lead` no trae campo `monday_id` tipado; el lugar disponible para persistencia es `lead.attributes`.

## Cambios aplicados
| Archivo | Tipo | Resumen |
|---------|------|---------|
| adapters/crm/monday_adapter.py | edit | Dedup por `text_mm2kjsap`, normalizacion de telefono, prioridad de ID existente, log `monday_dedup_found`, persistencia en `lead.attributes["monday_id"]` |
| tests/unit/test_monday_dedup.py | add | 5 tests: create, update por telefono, skip search con monday_id, normalizacion, telefono vacio |

## Tests / CI
- pytest tests/unit/test_monday_dedup.py -v: 5 passed
- pytest -v: 265 passed
- ruff: Found 1 error (fixed)
- black: 197 files unchanged
- mypy core/: Success (63 files)

## Decisiones de diseno
- `_find_item_by_phone` se volvio best-effort: si falla query GraphQL, log WARNING y retorna `None` para continuar flujo sin bloquear.
- `upsert_lead` ahora decide en este orden:
  1) `lead.external_id`
  2) `lead.attributes["monday_id"]`
  3) busqueda por telefono normalizado (`text_mm2kjsap`)
  4) create si no hay match.
- Se escribe tambien `COL_PHONE_DEDUPE` en payload para mantener llave de dedup consistente.

## Riesgos / pendientes
- Persistencia de `monday_id` queda en memoria del objeto `Lead` (`attributes`); guardado persistente en DB depende del flujo caller/repo fuera del alcance de C2.
- Si la columna `text_mm2kjsap` cambia en el board, dedup dejara de encontrar coincidencias hasta actualizar mapping/codigo.

## Comandos para reproducir
```bash
docker compose exec app pytest tests/unit/test_monday_dedup.py -v
docker compose exec app pytest -v
docker compose exec app ruff check . --fix
docker compose exec app black .
docker compose exec app mypy core/
```

## Siguiente paso sugerido
- C3: endurecer `STAGE_HIERARCHY` unidireccional (excepto `sin_interes`) para impedir retrocesos de etapa en Monday.

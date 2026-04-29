# [Sprint C · Mini-prompt C4] Slot syncing incremental

**Fecha:** 2026-04-28 · **Estado:** ☑ verificado · ☐ cerrado

## Objetivo
Reducir escrituras innecesarias a Monday enviando solo columnas modificadas en `update_item`, preservando ediciones manuales del asesor.

## Prompt enviado a Dev-AI
- Implementar snapshot y diff de columnas en `monday_adapter.py`
- Aplicar diff solo en update (create completo)
- Excluir columnas manuales/read-only del sync
- Guardar snapshot best-effort en `lead.attributes["monday_col_snapshot"]`

## Diagnostico reportado por Dev-AI
- `upsert_lead()` construia payload completo (`column_values + optional`) y lo enviaba siempre en update.
- No existia snapshot previo ni `last_synced` en adapter.
- Solo se persistia `lead.attributes["monday_id"]`.
- Columnas base siempre enviadas: telefono, dedupe, nombre, origen, vehiculo, resumen, canal, sincronizado, ultimo_contacto (+ etapa si `fsm_state`).
- Columnas opcionales construidas por `_build_optional_field_columns()` desde `field_map`.

## Cambios aplicados
| Archivo | Tipo | Resumen |
|---------|------|---------|
| adapters/crm/monday_adapter.py | edit | `COLUMNS_EXCLUDE_FROM_SYNC`, `_snapshot_lead_columns`, `_diff_columns`, logs `monday_sync_*`, diff integrado en update |
| tests/unit/test_slot_syncing.py | add | 7 tests puros de snapshot/diff/exclusiones |

## Implementacion tecnica
- Funciones puras agregadas a nivel modulo:
  - `_snapshot_lead_columns(column_values)`
  - `_diff_columns(current_snapshot, new_columns)`
- Comparacion estable por serializacion (`json.dumps(sort_keys=True)` para dicts).
- En `update_item`:
  - lee snapshot previo de `lead.attributes["monday_col_snapshot"]`
  - filtra columnas excluidas
  - calcula diff
  - si no hay cambios -> `monday_sync_skipped` y retorna sin llamar mutacion
  - si hay cambios -> `monday_sync_incremental` y envia solo diff
  - tras update exitoso guarda snapshot completo actual
- En `create_item` se conserva payload completo (sin diff).

## Columnas excluidas
- `multiple_person_mm2kdy8q` (Asignacion manual)
- `long_text_mm2k8vtc` (Notas manual)
- `pulse_log_mm2kwmcn` (read-only)
- `pulse_updated_mm2kcr4g` (read-only)

## Tests / CI
- `pytest tests/unit/test_slot_syncing.py -v` -> 7 passed
- `pytest -v` -> 279 passed
- `ruff check . --fix` -> All checks passed
- `black .` -> 199 files unchanged
- `mypy core/` -> Success (63 files)

## Riesgos / pendientes
- Snapshot es best-effort en `lead.attributes`; no persiste por DB en este mini-prompt.
- Si el proceso reinicia, primer sync posterior sera completo (esperado).
- Si el schema de columnas en Monday cambia, puede requerir ajustar exclusiones.

## Comandos para reproducir
```bash
docker compose exec app pytest tests/unit/test_slot_syncing.py -v
docker compose exec app pytest -v
docker compose exec app ruff check . --fix
docker compose exec app black .
docker compose exec app mypy core/
```

## Siguiente paso sugerido
- C5: resumen IA por evento + nota en Monday, reutilizando el payload incremental para minimizar ruido de sincronizacion.

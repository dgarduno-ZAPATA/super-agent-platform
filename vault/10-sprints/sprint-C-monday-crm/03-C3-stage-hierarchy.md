# [Sprint C · Mini-prompt C3] STAGE_HIERARCHY unidireccional

**Fecha:** 2026-04-28 · **Estado:** ☑ verificado · ☐ cerrado

## Objetivo
Evitar retrocesos de etapa en Monday y permitir solo avance unidireccional en la columna "Etapa Bot".

## Prompt enviado a Dev-AI
- Usar labels reales del board: Nuevo, Conversando, Calificando, Listo para Handoff, Handoff Hecho
- Ajustar `stage_map` (`won -> Handoff Hecho`)
- Implementar guard puro `_can_advance_stage`
- Integrar validacion en `change_stage()` con fetch best-effort del estado actual

## Diagnostico reportado por Dev-AI
- No existia guard de jerarquia en `change_stage()`.
- `crm_mapping.yaml` no tenia seccion de jerarquia.
- Labels reales de `color_mm2kvwdj` en board:
  - Nuevo
  - Conversando
  - Calificando
  - Listo para Handoff
  - Handoff Hecho

## Cambios aplicados
| Archivo | Tipo | Resumen |
|---------|------|---------|
| brand/crm_mapping.yaml | edit | `won` ahora mapea a `Handoff Hecho`; jerarquia documentada con labels reales (comentada para compatibilidad de schema estricto) |
| adapters/crm/monday_adapter.py | edit | Nuevo guard `_can_advance_stage`; fetch best-effort de etapa actual (`_get_item_stage_label`); bloqueo con log `monday_stage_blocked` |
| tests/unit/test_stage_hierarchy.py | add | 7 tests unitarios de reglas de avance/retroceso/reapertura/desconocidos |

## Jerarquia final (labels reales)
- index 0: Nuevo
- index 1: Conversando
- index 2: Calificando
- index 3: Listo para Handoff
- index 4: Handoff Hecho (terminal)

## Notas de negocio
- `won -> Handoff Hecho` aplicado.
- `lost` y `do_not_contact` permanecen mapeados a `Nuevo` por falta de etapa equivalente en board actual.

## Implementacion tecnica
- `change_stage()` ahora consulta estado actual de item con query GraphQL minima:
  `items(ids: [$item]) { column_values(ids: ["color_mm2kvwdj"]) { text } }`
- Fetch de estado actual es **best-effort** con timeout de 5s (`asyncio.wait_for`):
  - Si falla: `monday_stage_fetch_failed` y se permite el cambio.
  - Si existe estado y viola jerarquia: `monday_stage_blocked` y no actualiza.

## Tests / CI
- `pytest tests/unit/test_stage_hierarchy.py -v` -> 7 passed
- `pytest -v` -> 272 passed
- `ruff check . --fix` -> All checks passed
- `black .` -> 1 file reformatted (`test_stage_hierarchy.py`)
- `mypy core/` -> Success (63 files)

## Riesgos / pendientes
- `CRMMappingConfig` es `extra="forbid"`; por eso `stage_hierarchy`/`terminal_stages`/`special_stages` quedaron documentadas en comentario de YAML y la jerarquia operativa vive en constantes del adapter.
- Si Monday agrega nuevas etapas (ej. Sin Interes), se debe actualizar:
  - Board labels
  - Jerarquia en adapter
  - Comentario en `crm_mapping.yaml`

## Comandos para reproducir
```bash
docker compose exec app pytest tests/unit/test_stage_hierarchy.py -v
docker compose exec app pytest -v
docker compose exec app ruff check . --fix
docker compose exec app black .
docker compose exec app mypy core/
```

## Siguiente paso sugerido
- C4: slot syncing incremental (actualizar solo columnas Monday que cambiaron) para reducir ruido y escrituras innecesarias.

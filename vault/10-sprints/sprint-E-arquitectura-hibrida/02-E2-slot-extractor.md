---
# [Sprint E · Mini-prompt E2] Slot extraction determinístico

**Fecha:** 2026-04-28 · **Estado:** ☑ verificado · ☐ cerrado

## Objetivo
Implementar `SlotExtractor` standalone (puro, sin IO) con regla null estricta y merge determinístico por turno.

## Diagnóstico previo
- `LeadSlots` tiene 6 slots: `name`, `city`, `vehicle_interest`, `budget`, `phone`, `contact_preference`.
- `orchestrator` no extrae slots; solo clasifica intención y devuelve `fsm_event`.
- Slots actuales viven en `lead.attributes` (dict no tipado), con mezcla de claves legacy.
- Guards FSM dependen hoy de `name` y `phone` en contexto plano; no consumen `LeadSlots` directamente.

## Tabla de mapeo (para E3)
| LeadSlots field    | Claves legacy en flujo actual          |
|--------------------|----------------------------------------|
| vehicle_interest   | vehiculo_interes, interes_modelo,      |
|                    | vehicle_interest (mixto)               |
| city               | city, ciudad                           |
| name               | name (consistente)                     |
| phone              | phone (consistente)                    |
| budget             | budget (consistente)                   |

E3 será responsable de implementar mapper `LeadSlots -> dict legacy` para compatibilidad temporal con FSM/inbound.

## Cambios aplicados
| Archivo | Tipo | Resumen |
|---------|------|---------|
| core/services/slot_extractor.py | add | Extractor determinístico de slots + merge por turno + raw_matches |
| tests/unit/test_slot_extractor.py | add | 24 tests unitarios puros (sin mocks) |

## Validación
- `pytest tests/unit/test_slot_extractor.py -v` -> 24 passed
- `pytest -v` -> 201 passed
- `ruff check . --fix` -> All checks passed
- `black .` -> 1 file reformatted (`slot_extractor.py`)
- `mypy core/` -> Success (58 source files)

## Edge cases manejados
- `name`: bloquea genéricos (hola/gracias/etc.) y valores con dígitos.
- `city`: evita ambiguos (`aqui`, `casa`, `mexico` solo, etc.) y reduce falsos positivos.
- `vehicle_interest`: requiere trigger + keyword de vehículo; normaliza sin acentos.
- `budget`: soporta millones/mil/mdp, rango promedio y número agrupado; `1000` sin unidad queda `None`.
- `merge`: conserva slots previos cuando el turno actual no trae nuevo valor explícito.

## Riesgos para E3
- Sin mapper legacy, valores de `LeadSlots` no impactan automáticamente las rutas que leen `lead.attributes`.
- Algunas frases de ciudad tipo "de X" en oraciones complejas pueden requerir tuning adicional al integrar en flujo real.
- Presupuestos lingüísticos más complejos (ej. "uno punto dos") no están cubiertos aún.

## Siguiente paso sugerido
- E3: conectar `SlotExtractor` al pipeline de inbound con mapper legacy temporal y pruebas de compatibilidad FSM/guards.
---
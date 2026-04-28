---
# [Sprint A · Mini-prompt A2] Validar Sheet productivo + columnas

**Fecha:** 2026-04-28 · **Estado:** ☑ verificado · ☐ cerrado

## Objetivo
Confirmar que adapters/inventory/sheets_adapter.py retorna datos reales
del Google Sheet productivo, con campos críticos no vacíos.

## Prompt enviado a Dev-AI
- Diagnóstico de brand.yaml, sheets_adapter.py, schema.py
- Ejecución de get_products() en contenedor
- Verificación de campos críticos en primera unidad

## Diagnóstico reportado por Dev-AI
- INVENTORY_SHEET_URL y BRANCH_SHEET_URL no viven en brand.yaml:
  se inyectan como variables de entorno en runtime
- SheetsInventoryAdapter usa httpx.get con timeout=10.0, sin gspread
- Fallback YAML controlado por inventory_fallback_enabled (actualmente False)
- Cache TTL: 300s
- Sheet productivo URL activa:
  https://docs.google.com/spreadsheets/d/e/2PACX-[...]/pub?output=csv
- Total unidades retornadas: 268
- Primera unidad: INTERNATIONAL 4400 2018 · $1,015,000 · 932,712 km ·
  Motor MBE 210HP · Sucursal CAMIONES AEROPUERTO
- Campos críticos presentes y no vacíos: precio, km, motor, año,
  modelo, marca, centro ✅

## Cambios aplicados
| Archivo | Tipo | Resumen |
|---------|------|---------|
| ninguno | — | Sheet productivo validado sin cambios necesarios |

## Tests
- nuevos: ninguno
- modificados: ninguno
- pytest: 177 passed in 81.43s (0:01:21)
- ruff: All checks passed!
- black: All done! 173 files left unchanged.
- mypy: Success: no issues found in 53 source files (note: unused section(s): module = ['pytest.*'])

## Decisiones de diseño
- Las URLs de Sheets se inyectan vía env vars, no brand.yaml: correcto
  por arquitectura (secretos fuera del repo)
- inventory_fallback_enabled=False en producción: bot retorna vacío si
  Sheet falla, no alucina con YAML

## Riesgos / pendientes
- Fallback deshabilitado (False): si el Sheet falla en producción,
  get_products() devuelve [] y el bot debe manejar vacío sin alucinar
  (cubierto por reglas anti-alucinación de A1)
- Log de warning al entrar a fallback: no existe aún (Problema C del
  diagnóstico, no aplicó en esta sesión por fallback deshabilitado);
  queda como deuda técnica para Sprint B (logging completo)
- Columna "disponible" / availability: verificar si el Sheet tiene esta
  columna o si todas las unidades se exponen sin filtro de disponibilidad

## Verificación E2E
- Pendiente (A6)

## Siguiente paso sugerido
- A4: Fix FSM — revisar si send_document sigue siendo relevante dado
  que PDFs están fuera del alcance de Sprint A
---
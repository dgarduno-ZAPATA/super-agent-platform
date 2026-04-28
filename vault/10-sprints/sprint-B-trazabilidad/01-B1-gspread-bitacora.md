---
# [Sprint B · Mini-prompt B1] Adaptador gspread bitacora

**Fecha:** 2026-04-28 · **Estado:** ? verificado · ? cerrado

## Objetivo
Agregar un puerto de bitacora de conversacion y un adaptador gspread con upsert best-effort para registrar turnos sin afectar el flujo principal.

## Diagnostico previo
- `adapters/inventory/sheets_adapter.py` no usa gspread ni service account para inventario: consume CSV publico con `httpx.get(..., timeout=10.0)`.
- No existe helper reutilizable de autenticacion Google en inventario.
- `core/ports/` usa patron `Protocol` para puertos (`inventory_provider.py`, `llm_provider.py`, etc.).
- No existia `core/ports/conversation_log.py` ni `adapters/log/` previo a B1.
- No habia referencias previas a `CONVERSATION_LOG_SHEET_URL` en el repo.

## Implementacion
| Archivo | Tipo | Resumen |
|---------|------|---------|
| core/ports/conversation_log.py | add | `ConversationLogPort` (Protocol) con `log_turn(...)` async |
| adapters/log/gspread_log_adapter.py | add | `GspreadLogAdapter` con lazy init, upsert por `lead_id`, append para `lead_id=None`, manejo de errores best-effort |
| tests/unit/test_conversation_log_port.py | add | 3 pruebas unitarias del contrato del puerto con `AsyncMock` |
| pyproject.toml | edit | Se agrego `gspread>=6.1.4,<7.0.0` en dependencias |

## Autenticacion reutilizada/adaptada
- Como `sheets_adapter` actual no autentica contra Google (CSV publico), se implemento autenticacion en cascada para gspread:
  1. `GOOGLE_CREDENTIALS_JSON` (JSON en env var) -> `gspread.service_account_from_dict(...)`
  2. `GOOGLE_APPLICATION_CREDENTIALS` (ruta de archivo) -> `gspread.service_account(filename=...)`
  3. ADC fallback -> `gspread.auth.default()` + `gspread.authorize(...)`

## Variables de entorno
- Requerida para produccion: `CONVERSATION_LOG_SHEET_URL`.
- En diagnostico inicial no existian referencias en repo; debe configurarse en runtime (Diego).

## CI
- `docker compose exec app pytest -v` -> **246 passed**
- `docker compose exec app ruff check . --fix` -> **All checks passed**
- `docker compose exec app black .` -> **1 file reformatted, 190 files left unchanged**
- `docker compose exec app mypy core/` -> **Success: no issues found in 62 source files**

## Comandos de reproduccion
```bash
docker compose exec app pytest -v
docker compose exec app ruff check . --fix
docker compose exec app black .
docker compose exec app mypy core/
```

## Riesgos / pendientes para B2
- Si `CONVERSATION_LOG_SHEET_URL` no esta configurada, el adaptador no podra escribir (se captura error y no rompe flujo).
- Upsert por columna A depende de mantener `lead_id` como clave en hoja y headers esperados en `A1:G1`.
- Integracion al flujo real inbound aun pendiente (B2/B4).

## Siguiente paso sugerido
- B2: integrar debouncing 8s por JID/phone en `inbound_handler` y conectar escritura de bitacora en el punto de cierre de turno.
---

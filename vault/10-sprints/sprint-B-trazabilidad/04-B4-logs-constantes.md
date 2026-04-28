---
# [Sprint B · Mini-prompt B4] Cobertura de logs + constantes a brand

**Fecha:** 2026-04-28 · **Estado:** ☑ verificado · ☑ cerrado

## Objetivo
1) Cerrar gaps de logging con `lead_id=None/correlation_id=None`.
2) Mover mensajes hardcodeados de handoff/fricción a `brand.yaml`.
3) Integrar bitácora `ConversationLogPort` en el flujo real de inbound (best-effort).

## Diagnóstico previo
1. `rg -n "lead_id=None|lead_id=null|\"lead_id\": null" core/services/ --glob "*.py"`
```text
core/services/skills.py:182:            lead_id=None,
core/services/skills.py:197:                lead_id=None,
core/services/skills.py:212:                lead_id=None,
core/services/skills.py:220:                lead_id=None,
core/services/inbound_handler.py:136:            lead_id=None,
core/services/inbound_handler.py:657:                lead_id=None,
core/services/inbound_handler.py:670:                lead_id=None,
core/services/inbound_handler.py:678:                lead_id=None,
core/services/inbound_handler.py:692:                lead_id=None,
core/services/inbound_handler.py:705:                lead_id=None,
core/services/inbound_handler.py:713:                lead_id=None,
core/services/inbound_handler.py:854:                lead_id=None,
core/services/inbound_handler.py:867:                lead_id=None,
core/services/inbound_handler.py:875:                lead_id=None,
```

2. `rg -n "correlation_id=None|correlation_id=null" core/services/ --glob "*.py"`
```text
core/services/skills.py:183:            correlation_id=None,
core/services/skills.py:198:                correlation_id=None,
core/services/skills.py:213:                correlation_id=None,
core/services/skills.py:221:                correlation_id=None,
```

3. `brand/brand.yaml`
- No existía sección de mensajes de sistema.
- Se agregó sección nueva `system_messages`.

4. `rg -rn "HANDOFF_MSG|FRICTION_ESCALATION_MSG|Ya le avisé|Déjame conectarte" core/ --glob "*.py"`
```text
core/services/conversation_agent.py: (constantes hardcodeadas detectadas antes del cambio)
```

5. `core/services/inbound_handler.py`
- Punto final de turno exitoso: log `inbound_webhook_processed` + `return InboundHandleResult(status="processed", processed=True, ...)`.
- En ese punto sí hay acceso a `lead_profile.id`, `enriched_inbound_event.from_phone`, `updated_session.current_state` y `classification.intent`.

## Cambios aplicados
| Archivo | Tipo | Resumen |
|---------|------|---------|
| core/services/skills.py | edit | `inventory_query_started/ok` pasaron a `debug` cuando no hay IDs; TODO explícitos en `lead_id=None` y `correlation_id=None` |
| core/services/inbound_handler.py | edit | Corrección de `lead_id=None` en envíos WhatsApp (ahora usa `lead_id` real), integración best-effort de `conversation_log.log_turn(...)`, y `conversation_log_call_failed` |
| api/dependencies.py | edit | Inyección de `conversation_log` por DI con lazy import de `GspreadLogAdapter` y guard por `CONVERSATION_LOG_SHEET_URL` |
| core/brand/schema.py | edit | `SystemMessagesConfig` + campo `system_messages` en `BrandConfig` |
| brand/brand.yaml | edit | Nueva sección `system_messages` con textos exactos |
| core/services/conversation_agent.py | edit | Eliminadas constantes `HANDOFF_MSG`/`FRICTION_ESCALATION_MSG`; lectura desde `self._brand.brand.system_messages` |
| tests/unit/test_brand_config.py | add | tests de defaults y presencia de `system_messages` |
| tests/unit/services/test_inbound_handler.py | edit | test `conversation_log=None` safe |
| tests/unit/test_post_handoff.py | edit | ajustes por firma de `should_send_handoff_message(...)` |

## Tabla de gaps `lead_id=None`
| Archivo | Línea (actual) | Estado |
|---------|-----------------|--------|
| core/services/inbound_handler.py | 140 | `TODO` explícito (no disponible antes de crear lead) |
| core/services/skills.py | 183 | `TODO` explícito |
| core/services/skills.py | 200 | `TODO` explícito |
| core/services/skills.py | 217 | `TODO` explícito |
| core/services/skills.py | 227 | `TODO` explícito |

## Integración GspreadLogAdapter
- Se inyectó por **constructor/DI** (no lazy dentro de `core/`).
- Razón: respetar arquitectura hexagonal (`core` no importa `adapters`).
- En `api/dependencies.py`, si `CONVERSATION_LOG_SHEET_URL` no está configurada, se inyecta `None`.
- La llamada a `log_turn` en inbound es **best-effort** (try/except con warning).

## Criterios (outputs literales)
`rg -n "system_messages" brand/brand.yaml`
```text
31:system_messages:
```

`rg -n "SystemMessagesConfig" core/brand/schema.py`
```text
38:class SystemMessagesConfig(StrictConfigModel):
57:    system_messages: SystemMessagesConfig = Field(default_factory=SystemMessagesConfig)
```

`rg -n "HANDOFF_MSG|FRICTION_ESCALATION_MSG" core/services/conversation_agent.py`
```text
(sin resultados)
```

`rg -n "conversation_log|log_turn" core/services/inbound_handler.py`
```text
31:from core.ports.conversation_log import ConversationLogPort
80:        conversation_log: ConversationLogPort | None = None,
96:        self._conversation_log = conversation_log
922:        if self._conversation_log is None:
926:            await self._conversation_log.log_turn(
936:            logger.warning("conversation_log_call_failed", reason=str(exc))
```

`rg -n "lead_id=None" core/services/ --glob "*.py"`
```text
core/services/inbound_handler.py:140:            lead_id=None,
core/services/skills.py:183:            lead_id=None,
core/services/skills.py:200:                lead_id=None,
core/services/skills.py:217:                lead_id=None,
core/services/skills.py:227:                lead_id=None,
```

## CI
- `docker compose exec app pytest -v` → **258 passed**
- `docker compose exec app ruff check . --fix` → **Found 1 error (1 fixed, 0 remaining)**
- `docker compose exec app black .` → **3 files reformatted, 192 unchanged**
- `docker compose exec app mypy core/` → **Success: no issues found in 63 source files**

## Riesgos / deuda para Sprint C
- Persisten `lead_id=None`/`correlation_id=None` en `SkillRegistry` por diseño de scope (documentado con TODO).
- `conversation_log` depende de disponibilidad/env de `CONVERSATION_LOG_SHEET_URL` y runtime de `gspread`.
- Falta validación E2E con fila real en Sheet de bitácora en entorno productivo.

## Cierre Sprint B
- Este mini-prompt B4 queda cerrado.
- Sprint B queda cerrado.
---

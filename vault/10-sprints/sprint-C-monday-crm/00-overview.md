---
# Sprint C — Monday CRM productivo y disciplinado
**Estado:** ☐ planeado · ☐ en curso · ☑ cerrado
**Depende de:** Sprint E (slots limpios, cerrado)
**Bloquea a:** Sprint F, Sprint H

## Objetivo
Monday.com recibe datos limpios desde slots determinísticos,
embudo unidireccional, dedup por teléfono, resumen IA por evento,
slot syncing incremental, y alertas en DLQ.

## Scope IN
- Verificación E2E con board real (mutaciones GraphQL)
- Corrección de column IDs que fallan (warning detectado en A6)
- Dedup por teléfono antes de crear lead
- STAGE_HIERARCHY unidireccional (excepción: sin_interes)
- Slot syncing incremental (solo columnas que cambiaron)
- Generador de resumen IA por evento + nota en Monday
- Outbox + DLQ alerting (umbral configurable)

## Scope OUT
- Lead scoring (Sprint H)
- Tracking IDs Meta (Sprint H)

## Mini-prompts
- [x] C1 — Verificación E2E + corrección de column IDs
- [x] C2 — Dedup por teléfono antes de crear lead
- [x] C3 — STAGE_HIERARCHY unidireccional
- [x] C4 — Slot syncing incremental
- [x] C5 — Resumen IA por evento + nota en Monday
- [x] C6 — DLQ alerting con umbral configurable

## Criterios de aceptación
- [x] 0 leads con nombre = texto conversacional
- [x] 0 leads con ciudad = string ambiguo
- [x] Lead existente por teléfono → update; no duplicar
- [x] Estado solo avanza (test con intento de retroceso)
- [x] Resumen IA visible en Monday tras evento clave
- [x] DLQ > umbral → alerta (Sentry/log)
- [x] CI verde

## Verificación final
Item real en board de Monday con todos los campos correctos
tras conversación de prueba WhatsApp completa.
---

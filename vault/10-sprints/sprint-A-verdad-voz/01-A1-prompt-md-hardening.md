---
# [Sprint A · Mini-prompt A1] Endurecer brand/prompt.md

**Fecha:** 2026-04-28 · **Estado:** ☐ planeado · ☐ en curso · ☑ verificado · ☐ cerrado

## Objetivo
Reescribir brand/prompt.md con identidad blindada, reglas de formato estrictas,
anti-alucinación explícita y name gate para cotización/cita.

## Prompt enviado a Dev-AI
- Identidad en primera persona obligatoria (sin "un asesor de Raúl")
- Máximo 2 oraciones por turno
- Anti-alucinación con frases exactas de fallback
- Manejo de fallo técnico sin exponer errores al cliente
- Name gate solo para cotización formal y cita (no para resumen de specs)
- Resumen de specs como texto plano (sin PDF en este alcance)

## Diagnóstico reportado por Dev-AI
- prompt.md original: sin sección Anti-alucinación explícita, sin tercera persona detectada, sin PDF/send_document
- brand.yaml: persona = Raúl Rodríguez, empresa = SelecTrucks Zapata, sin campo de tono
- conversation_agent.py: no parsea secciones; inyecta prompt completo en _build_system_prompt
- Único lector del archivo: core/brand/loader.py:68

## Cambios aplicados
| Archivo | Tipo | Resumen |
|---------|------|---------|
| brand/prompt.md | edit | Reescritura con 7 secciones obligatorias nuevas/reemplazadas |

## Tests
- nuevos: ninguno (cambio solo Markdown)
- modificados: ninguno
- pytest: 177 passed in 100.33s (0:01:40)
- ruff: All checks passed!
- black: All done! 173 files left unchanged.
- mypy: Success: no issues found in 53 source files (nota: unused section module=['pytest.*'])

## Decisiones de diseño
- Sin PDF en Sprint A: bot entrega specs como resumen de texto en 1 mensaje
- Name gate activo solo para cotización formal y propuesta de cita
- No hay parser de secciones en el código: los encabezados ## son solo organización humana

## Riesgos / pendientes
- Tono declarado ausente en brand.yaml: el prompt asume tono directo/profesional sin respaldo en config
- CI bloqueado por Docker daemon apagado durante la sesión; re-verificar al levantar

## Verificación E2E
- Pendiente (A6)

## Siguiente paso sugerido
- A2: Validar Sheet productivo + columnas reales en adapters/inventory/sheets_adapter.py
---
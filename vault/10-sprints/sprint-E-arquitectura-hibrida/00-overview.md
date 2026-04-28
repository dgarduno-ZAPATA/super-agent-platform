---
# Sprint E — Arquitectura Híbrida (LLM como escritor)
**Estado:** ? planeado · ? en curso · ? cerrado
**Depende de:** Sprint A (cerrado)
**Bloquea a:** Sprint C (slots limpios), Sprint F

## Objetivo
El código decide intención y slots. El LLM solo redacta la respuesta
dentro de la acción que el código ya determinó. Las reglas comerciales
viven en código, no en el prompt.

## Problema que resuelve
- El LLM actualmente tiene libertad para "decidir" qué hacer, causando
  alucinaciones de inventario, slots sucios en Monday y comportamientos
  impredecibles.
- Los slots (nombre, ciudad, vehículo) se extraen del texto libre del
  cliente sin validación, contaminando el CRM.
- No hay anti-repetición: el bot puede dar la misma respuesta dos veces
  seguidas.

## Scope IN
- IntentRegistry: catálogo de intenciones reconocibles por el sistema
- SlotSchema: contrato de slots con regla null estricta
- Slot extraction determinístico (regex + reglas, sin LLM)
- Refactor conversation_agent.respond() para recibir acción + contexto
- Reglas comerciales codificadas (guards FSM endurecidos)
- Anti-repetición Jaccard (umbral 0.75) con regeneración
- Comportamiento post-handoff: bot no recalifica
- Gestión de fricción: confusión repetida ? escalar

## Scope OUT
- Bypass de LLM con respuestas pre-fabricadas
- Tracking IDs Meta (Sprint H)
- Lead scoring (Sprint H)

## Mini-prompts
- [x] E1 — Diseño del contrato: IntentRegistry, ActionRegistry, SlotSchema
- [x] E2 — Slot extraction determinístico con regla null estricta
- [x] E3 — Refactor conversation_agent.respond() para consumir contrato
- [x] E4 — Reglas comerciales (guards FSM endurecidos)
- [x] E5 — Anti-repetición Jaccard (umbral 0.75)
- [x] E6 — Comportamiento post-handoff
- [x] E7 — Gestión de fricción

## Criterios de aceptación
- [x] LLM nunca recibe libertad para decidir estado o slot
- [x] Slots devuelven null si no hay match explícito
- [x] Reglas comerciales en código, testeadas unitariamente
- [x] Anti-repetición regenera si Jaccard > 0.75
- [x] Bot no repregunta tras handoff hasta que cliente reabre
- [x] CI verde + tests unitarios para slot_extractor e intent_registry

## Verificación final
`pytest -v` ? tests de E2, E4, E5, E6 y E7 en verde.
Conversación de prueba donde: (1) slot inválido devuelve null,
(2) "quiero hablar con un humano" dispara handoff,
(3) respuesta repetida se regenera,
(4) fricción dispara mensaje de escalación.

## Hallazgos de A6 que E resuelve
- Etapa Monday "Listo para Handoff" incorrecta ? E4 (guards comerciales)
- inventory_query_empty en intent sin unidad seleccionada ? E2 (slots)
- Slots sucios en CRM ? E2 (null estricto)
---

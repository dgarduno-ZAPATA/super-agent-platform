---
# Sprint F — Handoff pasivo + alertas enriquecidas
**Estado:** ☐ planeado · ☐ en curso · ☑ cerrado
**Depende de:** Sprint E (cerrado), Sprint C (cerrado)
**Bloquea a:** —

## Objetivo
Cuando el asesor responde desde el número del bot, Raúl
se calla automáticamente. Las alertas al asesor incluyen
contexto completo para atender sin leer toda la conversación.

## Contexto técnico confirmado
- El bot (Raúl) y el asesor usan el MISMO número de WhatsApp.
- Evolution API entrega mensajes del asesor como webhooks
  con from_me=true y un message_id propio del bot/asesor.
- El bot debe distinguir sus propios mensajes de los del asesor
  para no auto-silenciarse.

## Scope IN
- Caché de message_id propios del bot (para no confundirlos
  con mensajes del asesor)
- Detección de mensaje saliente humano: from_me=true +
  message_id no está en caché del bot → silencio 60 min
- Alerta enriquecida al asesor (resumen, wa.me, vehículo,
  urgencia, acción sugerida)
- Diferenciación de estados post-handoff: Respondió /
  Interesado / Handoff activo / STOP / Error

## Scope OUT
- Lead scoring (Sprint H)
- Multimodal en alertas (Sprint G)

## Mini-prompts
- [x] F1 — Caché de message_id propios del bot
- [x] F2 — Detección from_me humano → silencio 60 min
- [x] F3 — Alerta enriquecida al asesor
- [x] F4 — Diferenciación de estados post-handoff

## Criterios de aceptación
- [ ] Si el asesor escribe desde el número del bot,
      Raúl calla exactamente 60 min para ese lead.
- [ ] Raúl NO se auto-silencia con sus propios mensajes.
- [ ] Test: bot envía mensaje → from_me=true → NO silencio.
- [ ] Test: asesor escribe → from_me=true → SÍ silencio 60 min.
- [ ] Alerta incluye: resumen IA, wa.me link, vehículo,
      nivel de urgencia, acción sugerida.
- [ ] CI verde.

## Verificación final
Conversación real: Diego escribe desde el número del bot
→ Raúl calla. Diego escribe desde número distinto → Raúl responde.
---

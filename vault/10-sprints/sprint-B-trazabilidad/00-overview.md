---
# Sprint B — Trazabilidad operativa completa
**Estado:** ☐ planeado · ☐ en curso · ☑ cerrado
**Depende de:** Sprint A (cerrado), Sprint E (cerrado)
**Bloquea a:** Sprint 14

## Objetivo
Bitácora gspread por conversación, debouncing 8s para ráfagas
de mensajes, typing presence proporcional, y cobertura 100%
de logs estructurados con los campos obligatorios.

## Scope IN
- Adaptador gspread que escribe bitácora por conversación
  en Google Sheet dedicado
- Puerto core/ports/conversation_log.py
- Debouncing 8s con asyncio.Lock por JID/phone en inbound_handler
- Typing presence proporcional a longitud de respuesta
- Delay log-normal antes de envío (simula latencia humana)
- Auditoría y cierre de gaps de logging (lead_id=None, branch=None)

## Scope OUT
- Lead scoring
- KPIs de conversión (Sprint 14)
- Mover HANDOFF_MSG y FRICTION_ESCALATION_MSG a brand/ (queda en B4)

## Mini-prompts
- [x] B1 — Adaptador gspread bitácora + puerto core/ports/
- [x] B2 — Debouncing 8s con lock por JID en inbound_handler
- [x] B3 — Typing presence + delay log-normal en evolution_adapter
- [x] B4 — Cobertura completa de logs + mover constantes a brand/

## Criterios de aceptación
- [ ] Cada conversación nueva genera fila en Sheet de bitácora
      con campos: lead_id, phone_masked, last_state, last_intent,
      summary, updated_at
- [ ] Ráfaga de 4 mensajes en <8s genera 1 sola respuesta del bot
- [ ] Typing presence aparece en WhatsApp antes del envío
- [ ] lead_id y correlation_id presentes en todos los logs críticos
- [ ] CI verde

## Verificación final
docker compose logs app | grep -E "conversation_log_|debounce_|typing_"
Sheet de bitácora con al menos 1 fila real tras conversación de prueba.
---

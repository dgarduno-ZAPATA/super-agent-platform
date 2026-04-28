---
# [Sprint B · Mini-prompt B2] Debouncing 8s por JID

**Fecha:** 2026-04-28 · **Estado:** ? verificado · ? cerrado

## Objetivo
Agrupar rafagas de mensajes por remitente para procesar solo el ultimo mensaje del grupo y evitar respuestas duplicadas/incoherentes.

## Diagnostico previo
- Metodo de entrada principal: `InboundMessageHandler.handle(...)` (async, linea ~108).
- Identificador de remitente en flujo actual: `InboundEvent.from_phone` (tambien existe `sender_id`, pero la conversacion se keyea por `from_phone`).
- Ya existia acumulacion simple por tiempo en `_should_defer_due_newer_inbound` con `asyncio.sleep(...)` y comparacion del ultimo inbound en repositorio.
- `InboundEvent` (en `core/domain/messaging.py`) define: `message_id`, `from_phone`, `sender_id`; para este sprint se uso `from_phone` como JID operativo.

## Implementacion
| Archivo | Tipo | Resumen |
|---------|------|---------|
| core/services/inbound_handler.py | edit | Debounce por JID con `_debounce_tasks`, `_debounce_latest`, `_debounce_lock`, `DEBOUNCE_SECONDS=8.0`, logs `debounce_cancelled/debounce_fired`, y enrutamiento via `_handle_with_debounce` |
| tests/unit/test_debounce.py | add | 4 tests async aislados para single, rafaga, ultimo mensaje y JIDs independientes |

## Detalle tecnico
- Se agregaron estructuras de modulo:
  - `_debounce_tasks: dict[str, asyncio.Task[bool]]`
  - `_debounce_latest: dict[str, InboundEvent]`
  - `_debounce_lock: asyncio.Lock`
  - `DEBOUNCE_SECONDS = 8.0`
- `handle(...)` ahora consulta `_should_defer_due_newer_inbound(jid=from_phone, event=...)`.
- Si llega un nuevo mensaje del mismo JID antes del timeout:
  - se cancela la task previa,
  - se loggea `debounce_cancelled`,
  - solo el ultimo mensaje llega a `debounce_fired` y continua flujo.
- Produccion: todo valor positivo de `message_accumulation_seconds` activa debounce en 8.0s.
- Admin/comandos: se excluyen de debounce eventos que no son `inbound_message` y textos tipo comando (`/...`).

## Grep diagnostico (literal)
Comando original solicitado con `grep` no disponible en PowerShell:
```text
grep : El término 'grep' no se reconoce como nombre de un cmdlet, función, archivo de script o programa ejecutable.
```
Equivalente ejecutado con `rg`:
```text
3:import asyncio
48:_debounce_tasks: dict[str, asyncio.Task[bool]] = {}
49:_debounce_latest: dict[str, InboundEvent] = {}
50:_debounce_lock = asyncio.Lock()
115:        if await self._silenced_user_repository.is_silenced(inbound_event.from_phone):
118:                phone=inbound_event.from_phone,
131:        conversation_id = self._build_conversation_id(enriched_inbound_event.from_phone)
161:            jid=enriched_inbound_event.from_phone,
...
108:    async def handle(self, raw_payload: dict[str, object]) -> InboundHandleResult:
```

## Criterios de aceptacion (grep literal)
```text
47:DEBOUNCE_SECONDS = 8.0
48:_debounce_tasks: dict[str, asyncio.Task[bool]] = {}
49:_debounce_latest: dict[str, InboundEvent] = {}
50:_debounce_lock = asyncio.Lock()
95:            DEBOUNCE_SECONDS if float(message_accumulation_seconds) > 0 else 0.0
1114:        should_process = await self._handle_with_debounce(jid=jid, event=event)
1117:    async def _handle_with_debounce(self, jid: str, event: InboundEvent) -> bool:
...
1129:                    "debounce_cancelled",
1161:                "debounce_fired",
```

## Tests / CI
- `docker compose exec app pytest tests/unit/test_debounce.py -v` -> **4 passed**
- `docker compose exec app pytest -v` -> **250 passed**
- `docker compose exec app ruff check . --fix` -> **All checks passed**
- `docker compose exec app black .` -> **192 files left unchanged**
- `docker compose exec app mypy core/` -> **Success: no issues found in 62 source files**

## Riesgos detectados para B3
- Estado debounce compartido a nivel modulo (`_debounce_tasks/_debounce_latest`): correcto para proceso unico, pero requiere cuidado en escenarios multi-worker/proceso.
- Si un proceso se reinicia durante ventana de debounce, se pierde la rafaga en memoria (no persistida).
- En futuras etapas puede convenir mover control de debounce a capa distribuida si hay escalado horizontal agresivo.

## Siguiente paso sugerido
- B3: implementar typing presence proporcional + delay log-normal en adaptador de mensajeria, manteniendo trazabilidad estructurada de tiempos.
---

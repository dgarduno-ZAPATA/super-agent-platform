---
# [Sprint B · Mini-prompt B3] Typing presence + delay log-normal

**Fecha:** 2026-04-28 · **Estado:** ? verificado · ? cerrado

## Objetivo
Enviar indicador de escritura antes de cada `send_text` y aplicar un delay humano log-normal proporcional a la longitud del mensaje.

## Diagnóstico previo
- Adaptador revisado: `adapters/messaging/evolution/adapter.py`.
- Método real de texto: `send_text(to, text, correlation_id)` (linea ~45), delegando a `_send_message` con endpoint `/message/sendText`.
- No existía typing presence en el adaptador antes de B3.
- No hay endpoint de typing documentado inline en comentarios/docstring del archivo.
- No existía utilidad previa de delay humano (`lognorm|human_delay|typing_delay` sin resultados).

## Endpoint de typing usado
- No encontrado documentado en el adaptador.
- Se aplicó estándar indicado en prompt:
  `POST /chat/sendPresence/{instance}`
  body: `{"number": "...", "options": {"presence": "composing"}}`

## Implementación
| Archivo | Tipo | Resumen |
|---------|------|---------|
| core/utils/human_delay.py | add | `compute_delay()` puro + `human_delay()` async con log `human_delay_applied` |
| adapters/messaging/evolution/adapter.py | edit | `send_text()` ahora ejecuta `_send_typing()` + `human_delay()` antes de `_send_message()`; typing best-effort con logs |
| tests/unit/test_human_delay.py | add | 5 tests para rango, texto corto/largo, vacío y cap máximo |

## Lo que se conservó vs cambió
- Conservado: flujo de envío real de texto (`_send_message` con `/message/sendText`) y normalización de número.
- Cambiado: en `send_text` se añadió pre-secuencia:
  1. `_send_typing(to)`
  2. `await human_delay(text, correlation_id)`
  3. envío real existente.

## Output literal de diagnóstico
`rg -n "typing|presence|sendPresence|sendTyping|is_typing" adapters/messaging/evolution/adapter.py`
```text
5:from typing import Any
```

`rg -n "send_message|sendText|sendMessage" adapters/messaging/evolution/adapter.py`
```text
45:        return await self._send_message(
46:            endpoint="/message/sendText",
54:        return await self._send_message(
63:        return await self._send_message(
77:        return await self._send_message(
150:    async def _send_message(
```

`rg -rn "lognorm|log_normal|human_delay|typing_delay" core/ adapters/ --glob "*.py"`
```text
(sin resultados)
```

## Criterios (rg literal)
`rg -n "human_delay|typing_presence" adapters/messaging/evolution/adapter.py`
```text
28:from core.utils.human_delay import human_delay
47:        await human_delay(text=text, correlation_id=correlation_id)
102:            logger.debug("typing_presence_sent", to=normalized_number[:4] + "***")
105:                "typing_presence_failed",
```

`rg -n "typing_presence_sent|typing_presence_failed" adapters/messaging/evolution/adapter.py`
```text
102:            logger.debug("typing_presence_sent", to=normalized_number[:4] + "***")
105:                "typing_presence_failed",
```

## Tests
- `test_short_text_gets_min_delay` ? PASS
- `test_long_text_gets_longer_delay` ? PASS
- `test_delay_always_in_range` ? PASS
- `test_empty_text_gets_min_delay` ? PASS
- `test_very_long_text_capped_at_max` ? PASS

## CI
- `docker compose exec app pytest tests/unit/test_human_delay.py -v` ? **5 passed**
- `docker compose exec app pytest -v` ? **255 passed**
- `docker compose exec app ruff check . --fix` ? **Found 1 error (1 fixed, 0 remaining)**
- `docker compose exec app black .` ? **1 file reformatted, 193 unchanged**
- `docker compose exec app mypy core/` ? **Success: no issues found in 63 source files**

## Riesgos detectados para B4
- El delay humano añade latencia percibida en pruebas E2E reales; conviene monitorear SLA por canal.
- `typing` es best-effort y depende de compatibilidad/versionado del endpoint de Evolution en producción.
- Si el proveedor rate-limitea presencia, habrá warnings pero el envío de texto seguirá (comportamiento esperado).

## Siguiente paso sugerido
- B4: cerrar cobertura de logs obligatorios y mover constantes de mensajes operativos a configuración de marca.
---

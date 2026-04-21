# Prueba Real de WhatsApp (Lead de Prueba)

## Paso 1 - Pre-requisitos
- Evolution API corriendo y con la instancia conectada a WhatsApp.
- Webhook de Evolution configurado apuntando a `https://<TU-DOMINIO>/webhooks/whatsapp`.
- Google Sheet de sucursales publicado como CSV publico, con al menos 1 sucursal activa.
- Google Sheet de inventario publicado como CSV publico, con al menos 3 productos.
- API desplegada con HTTPS valido y base de datos operativa.

## Paso 2 - Configurar `.env` para prueba
Variables minimas recomendadas:

```env
JWT_SECRET_KEY=<secret-32-chars-minimo>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<password-seguro>
INTERNAL_TOKEN=<token-interno>

DATABASE_URL=postgresql+asyncpg://app_user:<password>@db:5432/super_agent_platform
POSTGRES_USER=app_user
POSTGRES_PASSWORD=<password>
POSTGRES_DB=super_agent_platform

EVOLUTION_API_URL=https://<tu-evolution>
EVOLUTION_API_KEY=<api-key>
EVOLUTION_INSTANCE_NAME=<nombre-instancia>

BRANCH_SHEET_URL=https://docs.google.com/spreadsheets/d/e/.../pub?output=csv
INVENTORY_SHEET_URL=https://docs.google.com/spreadsheets/d/e/.../pub?output=csv

CAMPAIGN_SCHEDULER_ENABLED=true
LOG_LEVEL=INFO
```

## Paso 3 - Flujo de conversacion a probar
1. Lead nuevo envia `Hola`.
Esperado: greeting inicial con identidad de Raul.

2. Lead pregunta por producto (ejemplo: `Que tienes de remolques?`).
Esperado: respuesta consultando inventario (Sheets/fallback) con coincidencias.

3. Lead pregunta por sucursal (ejemplo: `Donde estan ubicados?`).
Esperado: respuesta con sucursal desde Google Sheets.

4. Lead envia `quiero un asesor`.
Esperado: handoff a humano + notificacion al agente/sucursal por WhatsApp.

5. Supervisor ejecuta take control:
`POST /api/v1/conversations/{lead_id}/take-control`
Esperado: bot en silencio para esa conversacion.

6. Supervisor ejecuta release control:
`POST /api/v1/conversations/{lead_id}/release-control`
Esperado: bot retoma atencion automatica.

## Paso 4 - Comandos de monitoreo durante prueba
Obtener token:

```bash
curl -sS -X POST "https://<TU-DOMINIO>/api/v1/auth/token" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<ADMIN_PASSWORD>"}'
```

Dashboard en tiempo real:

```bash
curl -sS "https://<TU-DOMINIO>/api/v1/dashboard/stats" \
  -H "Authorization: Bearer <TOKEN>"
```

Trazabilidad de conversacion:

```bash
curl -sS "https://<TU-DOMINIO>/api/v1/leads/<LEAD_ID>/trace" \
  -H "Authorization: Bearer <TOKEN>"
```

Logs de contenedores:

```bash
docker compose -f docker-compose.prod.yml logs -f --tail=200 app nginx
```

## Paso 5 - Troubleshooting por sintoma
- No llegan webhooks:
  - Verifica URL en Evolution y conectividad HTTPS.
  - Revisa `nginx` y `app` logs para requests a `/webhooks/whatsapp`.

- Responde pero no consulta inventario:
  - Verifica `INVENTORY_SHEET_URL` publica en CSV.
  - Confirma columnas esperadas en `brand/brand.yaml` (`inventory_columns`).

- No encuentra sucursal:
  - Verifica `BRANCH_SHEET_URL` publica en CSV.
  - Valida que exista sucursal activa y datos minimos.

- Handoff no notifica agente:
  - Revisa telefono del agente en Sheet de sucursales.
  - Revisa conectividad de Evolution API y credenciales.

- Endpoints protegidos fallan con 401:
  - Verifica `Authorization: Bearer <TOKEN>`.
  - Renueva token con `/api/v1/auth/token`.

- Dashboard o trace vacios:
  - Confirma que los eventos inbound/outbound se estan persistiendo en DB.
  - Revisa timezone/fechas de filtros (metricas de hoy).

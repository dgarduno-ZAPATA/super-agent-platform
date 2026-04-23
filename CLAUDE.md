# Super Agent Platform — Contexto del proyecto

Eres el asistente de ingeniería de este proyecto. Lee este archivo completo antes de cualquier cambio y respeta sus reglas sin excepción. Si una instrucción del usuario contradice este archivo, pregúntale antes de proceder.

## Qué estamos construyendo

Una plataforma conversacional comercial enterprise capaz de operar:
- **Outbound inteligente**: recuperación de leads dormidos, campañas configurables, cola priorizada, anti-baneo.
- **Inbound comercial**: atención en tiempo real, consulta de inventario, envío de fichas técnicas, handoff humano, sincronización con CRM.

No es un chatbot. Es una plataforma modular, white-label, cloud-portable y enterprise-ready. El código es un motor; la empresa vive en configuración, conectores y conocimiento.

## Stack técnico obligatorio

- **Lenguaje**: Python 3.11+
- **Framework web**: FastAPI
- **Base de datos**: PostgreSQL 16 con extensión pgvector (768 dims para RAG)
- **Migraciones**: Alembic
- **ORM**: SQLAlchemy 2.0 (modo async)
- **Validación**: Pydantic v2
- **Contenedores**: Docker + docker-compose para dev
- **Target de despliegue**: GCP Cloud Run `northamerica-south1` (código portable a AWS)
- **Tests**: pytest + pytest-asyncio — **147 passed**
- **Linter/formatter**: ruff + black (línea máxima: 100 chars)
- **Type checking**: mypy estricto en `core/`
- **Logs**: structlog con logs JSON estructurados

### Dependencias clave (pyproject.toml)

```
fastapi, uvicorn[standard], sqlalchemy[asyncio], asyncpg, alembic
pydantic>=2, pydantic-settings, structlog, pyyaml, httpx
pgvector                         # búsqueda vectorial en Postgres
apscheduler                      # scheduler de campañas outbound
python-jose                      # JWT para admin panel
python-multipart                 # file upload en FastAPI
pypdf, python-docx               # ingesta de documentos para RAG
sentry-sdk[fastapi]              # observabilidad en producción
openai                           # LLM fallback (GPT-4o-mini)
pyotp, qrcode[pil]               # 2FA TOTP
```

## Principios arquitectónicos NO NEGOCIABLES

### 1. Arquitectura hexagonal estricta
- `core/` contiene dominio, puertos (interfaces) y servicios. **Nunca** importa de `adapters/`.
- `adapters/` implementa los puertos definidos en `core/ports/`. Puede importar de `core/`.
- `api/` contiene routers FastAPI y dependencias (JWT, DI).
- La dirección de dependencias siempre apunta hacia el núcleo, nunca hacia afuera.

### 2. Configuración sobre hardcodeo
Nada crítico vive en código. Todo lo que cambia entre marcas vive en `brand/` (o `brands/<slug>/` para multi-marca):
- `brand.yaml` — identidad de marca
- `fsm.yaml` — estados FSM y transiciones declarativas
- `outbound_templates.yaml` — plantillas y campañas
- `prompt.md` — personalidad del Conversation Agent
- `products.yaml` — productos y metadatos
- `policies.yaml` — horarios, límites, reglas de baja, handoff
- `crm_mapping.yaml` — mapeo de etapas y campos al CRM
- `channels.yaml` — configuración de proveedores de mensajería
- `knowledge/` — documentos fuente para RAG

Si detectas que algo se está hardcodeando y debería vivir en `brand/`, **detente y avisa**.
Las sucursales y teléfonos de encargados se leen de Google Sheets (`BRANCH_SHEET_URL`), NO de YAML hardcodeado.

### 3. Postgres siempre, SQLite NUNCA
Race conditions con múltiples workers y SQLite son un dolor ya vivido. Postgres con transacciones serializables desde el día uno, sin excepciones. Ni para tests (usar `NullPool` + Postgres de test para aislar event loops).

### 4. FSM declarativa, no imperativa
La máquina de estados conversacional se define en `brand/fsm.yaml`, no como if-else. El código es un ejecutor genérico. Cada transición tiene:
- `evento` — qué pasó
- `guarda` — condición
- `acción` — efecto
- `nuevo_estado`
- `side_effects` — CRM, logs, envíos

El LLM **nunca** controla el flujo. El LLM genera texto dentro del estado actual; la FSM decide transiciones.

### 5. Outbox pattern obligatorio para CRM
Ninguna escritura directa al CRM. Todo va vía tabla `crm_outbox`, worker asíncrono con reintentos con backoff exponencial, y `crm_dlq` para fallos irrecuperables. La respuesta al cliente NUNCA espera a que el CRM conteste.

### 6. Dedup global de webhooks entrantes
Todo webhook entrante (WhatsApp, etc.) usa `message_id` como clave idempotente con constraint UNIQUE a nivel DB (índice parcial sobre `conversation_events`). No confíes en el proveedor.

### 7. Logs estructurados con correlation IDs
Todo log lleva: `conversation_id`, `lead_id`, `campaign_id`, `tenant_id`. Usa structlog. PII siempre enmascarada en logs (teléfonos, emails, nombres completos).

### 8. Secretos fuera del código
Nada de API keys en código o en `.env` commiteado. Usa `.env.local` (gitignored) en dev y Secret Manager en producción.

### 9. Tests para lógica de dominio
Todo lo que vive en `core/services/` y `core/domain/` debe tener tests unitarios. Los adaptadores tienen contract tests contra servicios reales en staging, no mocks en producción.

### 10. Portabilidad cloud
Nunca uses directamente APIs de GCP en el núcleo. Si necesitas storage, secretos, o colas, define un puerto en `core/ports/` y haz un adaptador en `adapters/`.

## Estructura del repositorio

```
super-agent-platform/
├── CLAUDE.md
├── pyproject.toml
├── docker-compose.yml
├── Dockerfile
├── core/
│   ├── domain/          # entidades puras (Lead, Session, ConversationEvent...)
│   ├── ports/           # interfaces (MessagingProvider, LLMProvider, repos...)
│   ├── services/        # lógica de negocio
│   ├── fsm/             # engine, guards, actions, schema
│   └── brand/           # loader de YAML de marca
├── adapters/
│   ├── messaging/       # EvolutionAdapter
│   ├── llm/             # VertexAdapter, OpenAIAdapter, ResilientLLMAdapter,
│   │                    # VertexEmbeddingAdapter, VertexTranscriptionAdapter
│   ├── crm/             # MondayCRMAdapter
│   ├── knowledge/       # PgVectorAdapter
│   └── storage/         # repos SQLAlchemy async + models.py
├── brand/               # configuración de SelecTrucks Zapata (marca piloto)
├── brands/              # otras marcas (white-label, una carpeta por slug)
├── scripts/
│   ├── new_brand.py     # scaffold de nueva marca
│   └── new_brand.sh
├── infra/
│   └── migrations/      # Alembic + 5 revisiones aplicadas
├── api/
│   ├── main.py
│   ├── dependencies.py
│   └── routers/         # webhooks, admin_panel, auth, campaigns...
└── tests/
    ├── unit/
    └── integration/
```

## Adaptadores implementados

```
adapters/messaging/evolution_adapter.py          WhatsApp via Evolution API
adapters/llm/vertex_adapter.py                   Gemini 2.5 Flash Lite
adapters/llm/openai_adapter.py                   GPT-4o-mini (fallback)
adapters/llm/resilient_adapter.py                Vertex → OpenAI (timeout 15s)
adapters/llm/vertex_embedding_adapter.py         text-embedding-004 (768 dims)
adapters/llm/vertex_transcription_adapter.py     Gemini audio → texto
adapters/crm/monday_adapter.py                   Monday.com CRM
adapters/knowledge/pgvector_adapter.py           búsqueda semántica
adapters/storage/repositories/
  lead_repo.py, session_repo.py
  conversation_event_repo.py, crm_outbox_repo.py
  outbound_queue_repo.py, knowledge_repo.py
  audit_log_repo.py, login_attempt_repo.py, admin_totp_repo.py
```

## Servicios en core/services/

```
conversation_agent.py          LLM + tool calling (skills)
orchestrator.py                clasificación de intenciones
inbound_handler.py             flujo completo de mensaje entrante
campaign_agent.py              envío de campañas outbound
campaign_worker.py             worker de cola outbound
crm_worker.py                  worker de outbox CRM
dashboard_service.py           métricas operativas
handoff_service.py             pausa/reanudación del bot
document_chunker.py            división de documentos para RAG
knowledge_ingestion_service.py ingesta + embedding + indexado
image_analysis_service.py      análisis de imágenes (Gemini vision)
audit_log_service.py           log inmutable de acciones admin
login_attempt_service.py       detección de lockout por IP
replay_engine.py               replay de conversaciones para tests
skills.py                      registry de tools del LLM
queue_worker.py                worker general de cola
```

## Migraciones aplicadas

```
20260415_0001 — MVP schema inicial (todas las tablas base)
20260417_0002 — knowledge_chunks + pgvector Vector(768)
20260422_0003 — audit_log table
20260422_0004 — login_attempts table
20260422_0005 — admin_totp table
```

## Secrets requeridos en Cloud Run (GCP Secret Manager)

```
JWT_SECRET_KEY          firma de tokens JWT del admin panel
ADMIN_PASSWORD          contraseña del usuario admin
INTERNAL_TOKEN          autenticación entre servicios internos
EVOLUTION_API_KEY       API key de Evolution API
EVOLUTION_BASE_URL      URL base de Evolution (ej: https://evo.zapata.com)
EVOLUTION_INSTANCE_NAME nombre de la instancia (ej: selectrucks-zapata)
DATABASE_URL            connection string de Cloud SQL (asyncpg)
VERTEX_PROJECT_ID       proyecto GCP para Vertex AI
OPENAI_API_KEY          fallback LLM
SENTRY_DSN              endpoint de Sentry para observabilidad
```

## Comandos útiles

```bash
# Dev
docker compose up -d
docker compose exec app pytest -v
docker compose exec app ruff check . --fix && docker compose exec app black .
docker compose exec app mypy core/

# Migraciones
docker compose exec app alembic upgrade head
docker compose exec app alembic revision --autogenerate -m "descripcion"

# Nueva marca
python scripts/new_brand.py <slug> "<Nombre de la marca>"

# Deploy
gcloud builds submit --tag gcr.io/chatbots-1-492817/super-agent-platform:latest
gcloud run deploy super-agent-platform \
  --image=gcr.io/chatbots-1-492817/super-agent-platform:latest \
  --region=northamerica-south1

# Rollback de emergencia
gcloud run services update-traffic super-agent-platform \
  --region=northamerica-south1 \
  --to-revisions=REVISION_ANTERIOR=100
```

## Aprendizajes dolorosos que NO se pueden repetir

Este proyecto nace de lecciones reales de Tono-Bot y Followup-Bot. No repitas estos errores:

1. **Race conditions por SQLite + múltiples workers en Render** → causó duplicados en Monday. Por eso Postgres desde el día uno.
2. **FSM imperativa acoplada al LLM** → causó loops repetitivos, respuestas ignoradas, alucinaciones que metían placeholders en el CRM. Por eso FSM declarativa.
3. **Acoplamiento a Evolution API** → bloqueó la migración a Meta Cloud API. Por eso `MessagingProvider` como puerto, con adaptadores intercambiables.
4. **Hardcodeo de nombres, textos y etapas** → hizo imposible agregar una segunda marca sin tocar código. Por eso `brand/`.
5. **Normalización de acentos mal hecha** → mandó fotos y ubicaciones equivocadas. Por eso validación explícita y tests de casos con acentos.
6. **Handoff agresivo con falsos positivos** → clientes legítimos eran pasados a humano sin razón. Por eso la detección de handoff es una skill testeable, no un regex enterrado.
7. **Linked Device ID (@lid)** de WhatsApp rompió comandos admin. Por eso la identificación de usuarios es explícita y testeada.
8. **Secrets guardados con valor vacío `""` en GCP** → Sentry y OpenAI fallaban silenciosamente. Verificar longitud del secret después de crearlo.

## Reglas de trabajo contigo (Claude Code)

1. **Una historia a la vez.** Si te pido algo vago como "implementa el sprint", pregúntame qué historia específica.
2. **Antes de escribir código, dime qué vas a hacer.** Plan corto en bullets, luego implementación.
3. **Si una decisión no está en este archivo y es importante, pregúntame.** No asumas.
4. **Si vas a introducir una dependencia nueva, dímelo y justifícala.**
5. **Después de cada cambio grande, corre los tests y el linter.**
6. **Nunca commites por mí.** Yo hago los commits cuando decido que la historia cerró.
7. **Si encuentras algo en el código existente que viola estos principios, avísame antes de tocarlo.**

## Sprint activo

**Sprint 14 — KPIs de negocio** (pendiente de iniciar)
- Dashboard de métricas comerciales: tasa de conversión por estado FSM, métricas de campañas outbound, tiempo promedio de respuesta.

## Historial de sprints

- Sprints 1–7: Fundamentos, mensajería, FSM, CRM outbox, handoff, admin panel, inventario Sheets, sucursales Sheets
- Sprint 8: Sentry + ResilientLLM (Vertex→OpenAI fallback)
- Sprint 9: Multimodal — audio (Vertex transcripción) + imágenes (Gemini vision)
- Sprint 10: RAG productivo — pgvector 768 dims + admin upload/list/delete
- Sprint 11: White-label + BRAND_PATH + scripts new_brand.py/.sh
- Sprint 12: Audit log + Login lockout + 2FA TOTP
- Sprint 13: CI verde (ruff/black) + documentación operativa (vault Obsidian)
- Sprint 14: KPIs de negocio (PENDIENTE)

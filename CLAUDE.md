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
- **Base de datos**: PostgreSQL 16 con extensión pgvector (para RAG)
- **Migraciones**: Alembic
- **ORM**: SQLAlchemy 2.0 (modo async)
- **Validación**: Pydantic v2
- **Contenedores**: Docker + docker-compose para dev
- **Target de despliegue**: GCP Cloud Run (pero código debe ser portable a AWS)
- **Tests**: pytest + pytest-asyncio
- **Linter/formatter**: ruff + black
- **Type checking**: mypy estricto en core/
- **Logs**: structlog con logs JSON estructurados

## Principios arquitectónicos NO NEGOCIABLES

### 1. Arquitectura hexagonal estricta
- `core/` contiene dominio, puertos (interfaces) y servicios. **Nunca** importa de `adapters/`.
- `adapters/` implementa los puertos definidos en `core/ports/`. Puede importar de `core/`.
- `infra/` contiene configuración de despliegue, migraciones, Docker.
- La dirección de dependencias siempre apunta hacia el núcleo, nunca hacia afuera.

### 2. Configuración sobre hardcodeo
Nada crítico vive en código. Todo lo que cambia entre marcas vive en `brand/`:
- `brand.yaml` — identidad de marca
- `funnel.yaml` — estados comerciales y transiciones
- `outbound_templates.yaml` — plantillas y campañas
- `prompt.md` — personalidad del Conversation Agent
- `products.yaml` — productos y metadatos
- `policies.yaml` — horarios, límites, reglas de baja, handoff
- `crm_mapping.yaml` — mapeo de etapas y campos al CRM
- `channels.yaml` — configuración de proveedores de mensajería
- `knowledge/` — documentos fuente para RAG

Si detectas que algo se está hardcodeando y debería vivir en `brand/`, **detente y avisa**.

### 3. Postgres siempre, SQLite NUNCA
Race conditions con múltiples workers y SQLite son un dolor ya vivido. Postgres con transacciones serializables desde el día uno, sin excepciones. Ni para tests (usa un Postgres de test, no SQLite).

### 4. FSM declarativa, no imperativa
La máquina de estados conversacional se define como datos (YAML o dict de Python), no como if-else. El código es un ejecutor genérico que lee la definición. Cada transición tiene:
- `evento` (qué pasó)
- `guarda` (condición)
- `acción` (efecto)
- `nuevo_estado`
- `side_effects` (CRM, logs, envíos)

El LLM **nunca** controla el flujo. El LLM genera texto dentro del estado actual; la FSM decide transiciones.

### 5. Outbox pattern obligatorio para CRM
Ninguna escritura directa al CRM. Todo va vía tabla `crm_outbox`, worker asíncrono con reintentos con backoff exponencial, y `crm_dlq` para fallos irrecuperables. La respuesta al cliente NUNCA espera a que el CRM conteste.

### 6. Dedup global de webhooks entrantes
Todo webhook entrante (WhatsApp, etc.) usa `message_id` como clave idempotente con constraint UNIQUE a nivel DB. No confíes en el proveedor.

### 7. Logs estructurados con correlation IDs
Todo log lleva: `conversation_id`, `lead_id`, `campaign_id`, `tenant_id`. Usa structlog. PII siempre enmascarada en logs (teléfonos, emails, nombres completos).

### 8. Secretos fuera del código
Nada de API keys en código o en `.env` commiteado. Usa `.env.local` (gitignored) en dev y Secret Manager en producción.

### 9. Tests para lógica de dominio
Todo lo que vive en `core/services/` y `core/domain/` debe tener tests unitarios. Los adaptadores tienen contract tests contra servicios reales en staging, no mocks en producción.

### 10. Portabilidad cloud
Nunca uses directamente APIs de GCP en el núcleo. Si necesitas storage, secretos, o colas, define un puerto en `core/ports/` y haz un adaptador en `adapters/`.

## Estructura del repositorio
super-agent-platform/
├── CLAUDE.md
├── README.md
├── .gitignore
├── .env.example
├── pyproject.toml
├── docker-compose.yml
├── Dockerfile
├── core/
│   ├── domain/
│   ├── ports/
│   └── services/
├── adapters/
│   ├── crm/
│   ├── messaging/
│   ├── llm/
│   ├── knowledge/
│   └── storage/
├── brand/
│   ├── brand.yaml
│   ├── funnel.yaml
│   ├── outbound_templates.yaml
│   ├── prompt.md
│   ├── products.yaml
│   ├── policies.yaml
│   ├── crm_mapping.yaml
│   ├── channels.yaml
│   └── knowledge/
├── infra/
│   ├── docker/
│   └── migrations/
├── api/
└── tests/
├── unit/
└── integration/

## Aprendizajes dolorosos que NO se pueden repetir

Este proyecto nace de lecciones reales de Tono-Bot y Followup-Bot. No repitas estos errores:

1. **Race conditions por SQLite + múltiples workers en Render** → causó duplicados en Monday. Por eso Postgres desde el día uno.
2. **FSM imperativa acoplada al LLM** → causó loops repetitivos, respuestas ignoradas, alucinaciones que metían placeholders en el CRM. Por eso FSM declarativa.
3. **Acoplamiento a Evolution API** → bloqueó la migración a Meta Cloud API. Por eso `MessagingProvider` como puerto, con adaptadores intercambiables.
4. **Hardcodeo de nombres, textos y etapas** → hizo imposible agregar una segunda marca sin tocar código. Por eso `brand/`.
5. **Normalización de acentos mal hecha** → mandó fotos y ubicaciones equivocadas. Por eso validación explícita y tests de casos con acentos.
6. **Handoff agresivo con falsos positivos** → clientes legítimos eran pasados a humano sin razón. Por eso la detección de handoff es una skill testeable, no un regex enterrado.
7. **Linked Device ID (@lid)** de WhatsApp rompió comandos admin. Por eso la identificación de usuarios es explícita y testeada.

## Reglas de trabajo contigo (Claude Code)

1. **Una historia a la vez.** Si te pido algo vago como "implementa el sprint", pregúntame qué historia específica.
2. **Antes de escribir código, dime qué vas a hacer.** Plan corto en bullets, luego implementación.
3. **Si una decisión no está en este archivo y es importante, pregúntame.** No asumas.
4. **Si vas a introducir una dependencia nueva, dímelo y justifícala.**
5. **Después de cada cambio grande, corre los tests y el linter.**
6. **Nunca commites por mí.** Yo hago los commits cuando decido que la historia cerró.
7. **Si encuentras algo en el código existente que viola estos principios, avísame antes de tocarlo.**

## Sprint activo

**Sprint 2 — Prompt 2.3 (Webhook inbound Evolution).** Objetivo: exponer el endpoint `/webhooks/whatsapp` para recibir eventos entrantes, aplicar dedup, persistir en repos async y registrar logs estructurados, sin enviar respuesta al usuario.

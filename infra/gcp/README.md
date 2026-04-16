# GCP Deploy (Cloud Run + Cloud SQL + Secret Manager)

## Prerrequisitos

- `gcloud` instalado y autenticado (SDK 565.0.0 o compatible).
- Proyecto seleccionado o accesible: `chatbots-1-492817`.
- Permisos para:
  - Cloud Run
  - Cloud SQL Admin
  - Secret Manager Admin
  - Artifact Registry Admin
  - Cloud Build Editor (para builds/deploy relacionados)
- `bash`, `curl`, `psql`, `python3` disponibles en tu entorno.
- `poetry` (o `alembic`) disponible para correr migraciones locales con `migrate.sh`.

## Flujo recomendado

1. `setup.sh`
2. `migrate.sh`
3. `deploy.sh`

## 1) Setup de infraestructura base

```bash
bash infra/gcp/setup.sh
```

Qué hace:

- Habilita APIs: Cloud Run, Cloud SQL Admin, Secret Manager, Artifact Registry, Cloud Build.
- Reutiliza una instancia PostgreSQL existente si hay una; si no, crea una `db-f1-micro` PostgreSQL 16.
- Crea (si falta) la DB `super_agent_platform`.
- Crea o actualiza el usuario `app_user` (rota password en cada corrida).
- Intenta habilitar `pgvector` en la DB (`CREATE EXTENSION IF NOT EXISTS vector`).
- Crea (si falta) repositorio Docker en Artifact Registry.
- Crea/actualiza secretos en Secret Manager:
  - `DATABASE_URL`
  - `EVOLUTION_BASE_URL`
  - `EVOLUTION_API_KEY`
  - `EVOLUTION_INSTANCE_NAME`
- Imprime resumen final de recursos creados/reutilizados/actualizados.

## 2) Migraciones hacia Cloud SQL

```bash
bash infra/gcp/migrate.sh
```

Qué hace:

- Levanta Cloud SQL Proxy local.
- Lee `DATABASE_URL` desde Secret Manager.
- Construye una URL TCP local para alembic.
- Ejecuta `alembic upgrade head`.
- Verifica tablas clave con un `SELECT` a `information_schema.tables`.

## 3) Deploy de la app a Cloud Run

```bash
bash infra/gcp/deploy.sh
```

Qué hace:

- Build de imagen Docker con target `prod`.
- Push a Artifact Registry.
- Deploy de `super-agent-platform` en Cloud Run (`northamerica-south1`) con:
  - `--add-cloudsql-instances`
  - secretos como variables de entorno
  - `min-instances=0`, `max-instances=2`
  - `cpu=1`, `memory=512Mi`, `timeout=300`
  - `--allow-unauthenticated`
  - `--port=8000`
- Imprime URL final del servicio.

## Verificación rápida

```bash
curl -i "https://<CLOUD_RUN_URL>/health"
```

Debe regresar `200` y payload con `{"status":"ok", ...}`.

## Ver logs

```bash
gcloud run logs read super-agent-platform \
  --project chatbots-1-492817 \
  --region northamerica-south1 \
  --limit 100
```

## Rollback (deploy de revisión previa)

Cloud Run no tiene un comando `rollback` directo. Para volver a una revisión previa:

1. Lista revisiones:

```bash
gcloud run revisions list \
  --service super-agent-platform \
  --project chatbots-1-492817 \
  --region northamerica-south1
```

2. Reasigna tráfico a la revisión previa:

```bash
gcloud run services update-traffic super-agent-platform \
  --project chatbots-1-492817 \
  --region northamerica-south1 \
  --to-revisions <REVISION_NAME>=100
```

Alternativa: redeploy de una imagen previa con `gcloud run deploy --image ...`.


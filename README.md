# Super Agent Platform

[![CI](https://github.com/your-org/super-agent-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/super-agent-platform/actions/workflows/ci.yml)

Plataforma conversacional comercial enterprise para flujos inbound y outbound.
Construida con FastAPI, SQLAlchemy async y PostgreSQL como base operativa.
Diseñada con arquitectura hexagonal para soportar marcas, canales y conectores intercambiables.

## Requisitos

- Python 3.11 o superior
- Poetry instalado
- PostgreSQL 16 disponible para desarrollo local

## Levantar entorno local

1. Crea el entorno e instala dependencias con `poetry install`.
2. Copia variables de entorno con `Copy-Item .env.example .env.local`.
3. Ajusta `DATABASE_URL` y cualquier valor local necesario en `.env.local`.
4. Verifica la base del proyecto con `poetry run pytest`, `poetry run ruff check .`, `poetry run black --check .` y `poetry run mypy core`.

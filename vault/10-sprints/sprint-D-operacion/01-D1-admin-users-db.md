---
title: D1 Admin Users DB
tags:
  - sprint
  - sprint-d
  - auth
  - migration
aliases:
  - D1 Admin Users
---

# D1 · Migrar auth a `admin_users` con bcrypt

## Objetivo
Reemplazar la validacion hardcodeada por env vars en `/api/v1/auth/token` con autenticacion contra DB usando bcrypt.

## Cambios principales
- Se agrego `passlib[bcrypt]` y pin de compatibilidad `bcrypt>=4,<5`.
- Nuevo modelo ORM `AdminUserModel` (`admin_users`).
- Nueva migracion: `20260429_0007_add_admin_users_table.py`.
- Nuevo puerto: `core/ports/admin_user_repository.py`.
- Nuevo repositorio: `adapters/storage/repositories/admin_user_repo.py`.
- Nuevo servicio: `core/services/admin_auth_service.py`.
- `api/routers/auth.py` ahora autentica con DB y actualiza `last_login_at`.
- `api/dependencies.py` incorpora DI para repo/service de admin users.
- `api/main.py` ahora valida usuarios admin activos en DB con warning no bloqueante.
- Script nuevo: `scripts/migrate_admin_user.py` (idempotente, usa `ADMIN_USERNAME` y `ADMIN_PASSWORD`).
- Tests nuevos: `tests/unit/auth/test_admin_auth_service.py`.

## Notas tecnicas
> [!warning]
> `passlib 1.7.4` con `bcrypt 5.x` rompe hashing en runtime. Se fijo `bcrypt>=4,<5` para compatibilidad estable.

## CI
- `docker compose exec app pytest -v` -> 300 passed.
- `docker compose exec app ruff check . --fix` -> All checks passed.
- `docker compose exec app black .` -> OK.
- `docker compose exec app mypy core/` -> Success (66 source files).

## Relacion
- Volver a [[00-overview|overview del Sprint D]].

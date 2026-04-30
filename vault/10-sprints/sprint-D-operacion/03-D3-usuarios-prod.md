---
title: D3 Usuarios iniciales y producción
tags:
  - sprint
  - sprint-d
  - auth
  - onboarding
aliases:
  - D3 usuarios prod
---

# D3 · Usuarios iniciales + migración producción

## Objetivo
- Quitar dependencia operativa de `ADMIN_*` para login normal.
- Verificar usuarios admin activos en DB durante startup.
- Mantener `ADMIN_*` solo para bootstrap inicial.

## Cambios
- `core/config.py`
  - Campos `admin_username`, `admin_password`, `admin_username_2`, `admin_password_2` marcados como `DEPRECATED`.
  - Defaults vacíos (`""`) y `repr=False` en passwords.
- `api/main.py`
  - Nuevo check `_check_admin_users(session, logger)` con conteo SQL de usuarios activos.
  - Logs:
    - warning `no_active_admin_users` si count=0 con hint del script.
    - info `admin_users_ok` si count>0 con `active_count`.
  - Startup ya no depende de `ADMIN_PASSWORD`.
- `scripts/migrate_admin_user.py`
  - Mantiene migración por env vars.
  - Soporta `python scripts/migrate_admin_user.py username password`.
  - Conserva idempotencia (`ON CONFLICT DO NOTHING`) y bcrypt vía `AdminAuthService.hash_password()`.
- `docs/ADMIN-ONBOARDING.md`
  - Flujo de alta por panel y bootstrap vía Cloud Shell.
- `tests/unit/test_startup_check.py`
  - 2 pruebas nuevas para warning/info del startup check.

## CI D3
- `pytest -v` → 308 passed.
- `ruff check . --fix` → All checks passed.
- `black .` → unchanged (211 files left unchanged).
- `mypy core/` → Success (66 source files).

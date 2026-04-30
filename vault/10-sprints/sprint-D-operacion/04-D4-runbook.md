---
title: D4 Runbook operativo y fix bcrypt
tags:
  - sprint
  - sprint-d
  - runbook
  - auth
aliases:
  - D4 runbook
---

# D4 - Runbook operativo + fix bcrypt warning

## Objetivo
- Cerrar Sprint D con runbook operativo del panel admin.
- Eliminar ruido de warning passlib/bcrypt en logs del modulo admin.

## Cambios
- `core/services/admin_auth_service.py`
  - Se agrega `warnings.filterwarnings(...)` acotado al warning
    `error reading bcrypt version` antes de inicializar `CryptContext`.
- `vault/30-runbooks/admin-panel.md`
  - Runbook operativo completo para acceso, usuarios, rotacion,
    deploy, migraciones y troubleshooting.
- `vault/10-sprints/sprint-D-operacion/00-overview.md`
  - Historias D1-D4 marcadas en [x].
  - Estado actualizado a `☑ cerrado`.
  - Seccion de tooling pendiente: gitleaks, bandit, Dependabot,
    OpenTelemetry.

## Validacion tecnica
- Import del modulo sin warning:
  - `docker compose exec app python -c "from core.services.admin_auth_service import AdminAuthService"`
- CI:
  - `pytest -v`
  - `ruff check .`
  - `black --check .`
  - `mypy core/`

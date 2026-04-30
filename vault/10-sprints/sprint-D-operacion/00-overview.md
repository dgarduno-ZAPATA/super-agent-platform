---
title: Sprint D Operacion Overview
tags:
  - sprint
  - sprint-d
  - auth
aliases:
  - Sprint D Overview
---

# Sprint D - Operacion

## Historias
- [x] [[01-D1-admin-users-db|D1 - Migrar auth a admin_users con bcrypt]]
- [x] [[02-D2-crud-usuarios|D2 - CRUD de usuarios en panel/API]]
- [x] [[03-D3-usuarios-prod|D3 - Usuarios iniciales + produccion]]
- [x] [[04-D4-runbook|D4 - Runbook operativo + fix bcrypt warning]]

## Estado
- Sprint D: ☑ cerrado

## Validaciones
- `pytest -v`: 308 passed.
- `ruff check .`: OK.
- `black --check .`: OK.
- `mypy core/`: OK.

## Tooling pendiente (futuros sprints)
- gitleaks
- bandit
- Dependabot
- OpenTelemetry

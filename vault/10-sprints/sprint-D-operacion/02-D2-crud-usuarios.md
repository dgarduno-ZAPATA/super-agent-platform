---
title: D2 CRUD Usuarios
tags:
  - sprint
  - sprint-d
  - auth
  - admin-panel
aliases:
  - D2 CRUD Admin Users
---

# D2 · CRUD de usuarios (API) + split UI a D2-b

## Objetivo
Permitir crear, listar, activar/desactivar y cambiar contraseña de usuarios admin desde API.
La sección de panel se divide a D2-b por restricción de tamaño de historia.

## Backend
- `GET /api/v1/auth/users`
- `POST /api/v1/auth/users`
- `DELETE /api/v1/auth/users/{user_id}` (soft delete: `is_active=false`)
- `PUT /api/v1/auth/users/{user_id}/status` (activar/inactivar)
- `PUT /api/v1/auth/users/{user_id}/password`

Reglas:
- JWT requerido en todos los endpoints.
- No se expone `password_hash`.
- No se permite desactivarse a sí mismo.
- Validación de username y password en API.

## Panel admin
- Split a D2-b.
- Motivo: la implementación de UI excedía el umbral de `> 200` líneas nuevas en `api/routers/admin_panel.py`.
- En D2 actual no se dejó código parcial de UI para evitar deuda/inconsistencia.

## D2-b — UI panel
- Archivo tocado: `api/routers/admin_panel.py` (único de código).
- Se agregó pestaña `Usuarios` en el nav (después de `Seguridad` y antes de `Registro actividad`).
- Se agregó sección `usuarios-view` con:
  - Formulario crear usuario (`new-username`, `new-password`, `btn-create-user`).
  - Tabla de usuarios (`users-table`, `users-tbody`) con estado y acciones.
  - Modal de cambio de contraseña (`modal-change-password` + botones guardar/cancelar).
- Se integró JS plano para:
  - `loadUsuarios()` (GET `/api/v1/auth/users`)
  - `createUser()` (POST `/api/v1/auth/users`)
  - `toggleUserStatus()` (PUT `/api/v1/auth/users/{id}/status`)
  - `openChangePassword()` + `saveNewPassword()` (PUT `/api/v1/auth/users/{id}/password`)
- Se integró en `setActiveTab("usuarios")` para cargar datos al entrar.
- Se usó `escapeHtml()` existente para render seguro en tabla.
- Mensajes de error y feedback inline; no se usó `alert()`.

### CI D2-b
- `docker compose exec app pytest -v` → 306 passed.
- `docker compose exec app ruff check . --fix` → All checks passed.
- `docker compose exec app black .` → 210 files left unchanged.
- `docker compose exec app mypy core/` → Success (66 source files).

## CI
- `pytest -v`: 306 passed.
- `ruff check . --fix`: OK.
- `black .`: OK.
- `mypy core/`: Success.

## Riesgos siguientes
- Falta control por roles/permissions granulares para acciones de usuarios.
- No hay auditoría específica por endpoint CRUD de usuarios (acción detallada por target user).

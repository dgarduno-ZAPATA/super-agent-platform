# Cómo crear un nuevo usuario admin

## Opción A — Desde el panel (recomendado)
1. Entra a `/admin` con tus credenciales.
2. Ve a la pestaña "Usuarios".
3. Llena el formulario con username y contraseña.
4. Clic en "Crear usuario".

## Opción B — Desde Cloud Shell (primer usuario)
```bash
gcloud run jobs create create-admin \
  --image=gcr.io/chatbots-1-492817/super-agent-platform:latest \
  --region=northamerica-south1 \
  --set-secrets="DATABASE_URL=DATABASE_URL:latest" \
  --command="python" \
  --args="scripts/migrate_admin_user.py,USERNAME,PASSWORD" \
  --execute-now --wait \
  --project=chatbots-1-492817
```

## Política de contraseñas
- Mínimo 8 caracteres.
- Cambiar contraseña inicial en primer acceso.
- No compartir credenciales entre usuarios.

## Acceso al panel
URL: https://super-agent-platform-188929108695.northamerica-south1.run.app/admin

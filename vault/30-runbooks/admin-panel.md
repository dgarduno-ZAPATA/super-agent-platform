# Runbook - Panel Admin

## Acceso
URL: https://super-agent-platform-188929108695.northamerica-south1.run.app/admin
Usuario por defecto: admin

## Gestion de usuarios

### Crear usuario nuevo (desde panel)
1. Login en /admin
2. Pestana "Usuarios"
3. Completar formulario Username + Contrasena
4. Clic "Crear usuario"

### Crear primer usuario (sin panel - Cloud Shell)
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

### Cambiar contrasena (desde panel)
1. Pestana "Usuarios"
2. Boton "Cambiar contrasena" en la fila del usuario
3. Ingresar nueva contrasena (min. 8 chars) y confirmar

### Desactivar usuario
1. Pestana "Usuarios"
2. Boton "Desactivar" en la fila del usuario
Nota: no puedes desactivar tu propio usuario.

## Rotacion de credenciales

### Rotar ADMIN_PASSWORD en Secret Manager
Solo necesario para bootstrap. El login ya usa DB.
```bash
echo -n "NUEVA_PASSWORD" | gcloud secrets versions add \
  ADMIN_PASSWORD --data-file=- --project=chatbots-1-492817
```

### Verificar usuarios activos en produccion
```bash
gcloud run jobs create check-admins \
  --image=gcr.io/chatbots-1-492817/super-agent-platform:latest \
  --region=northamerica-south1 \
  --set-secrets="DATABASE_URL=DATABASE_URL:latest" \
  --command="python" \
  --args="scripts/migrate_admin_user.py" \
  --execute-now --wait \
  --project=chatbots-1-492817
```

## Deploy

### Deploy manual desde master
```bash
git checkout master
git pull origin master
# El push a master dispara GitHub Actions automaticamente
```

### Verificar deploy exitoso
1. GitHub Actions -> Deploy to Cloud Run -> verde
2. URL del panel responde 200

### Rollback
En GCP Console -> Cloud Run -> super-agent-platform
-> Revisiones -> seleccionar revision anterior
-> Enviar 100% del trafico

## Migracion de DB

### Aplicar migraciones en produccion
Las migraciones corren automaticamente al iniciar
el contenedor (ver api/main.py startup).

### Verificar estado de migraciones
```bash
gcloud run jobs create alembic-check \
  --image=gcr.io/chatbots-1-492817/super-agent-platform:latest \
  --region=northamerica-south1 \
  --set-secrets="DATABASE_URL=DATABASE_URL:latest" \
  --command="python" \
  --args="-m,alembic,current" \
  --execute-now --wait \
  --project=chatbots-1-492817
```

## Troubleshooting comun

### "Credenciales incorrectas" en login
1. Verificar que el usuario existe en la tabla admin_users
2. Verificar que is_active = true
3. El campo username es case-sensitive

### Panel no carga
1. Verificar que el deploy fue exitoso en GitHub Actions
2. Revisar logs: GCP Console -> Cloud Run -> Logs

### Bot no responde en WhatsApp
1. Verificar Evolution API en EasyPanel
2. Revisar logs de Cloud Run para errores de webhook

## Variables de entorno criticas
| Variable | Descripcion | Donde vive |
|----------|-------------|------------|
| DATABASE_URL | Conexion PostgreSQL | Secret Manager |
| JWT_SECRET_KEY | Firma de tokens admin | Secret Manager |
| EVOLUTION_API_KEY | API de WhatsApp | Secret Manager |
| MONDAY_API_KEY | CRM | Secret Manager |
| SHEET_CSV_URL | Inventario | Cloud Run env |

## Contacto tecnico
- Repo: github.com/dgarduno-ZAPATA/super-agent-platform
- GCP Project: chatbots-1-492817
- Region: northamerica-south1

# Deploy en Produccion (Ubuntu)

## 1. Requisitos
- Ubuntu 22.04+ con acceso sudo.
- Docker Engine y Docker Compose Plugin instalados.
- Dominio apuntando al IP publico del servidor (registro A/AAAA).
- Puertos 80 y 443 abiertos en firewall/security group.

## 2. Clonar repo y configurar .env
```bash
git clone <tu-repo> super-agent-platform
cd super-agent-platform
cp .env.example .env
```

Edita `.env` con valores reales, especialmente:
- `JWT_SECRET_KEY`
- `ADMIN_PASSWORD`
- `INTERNAL_TOKEN`
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
- `DATABASE_URL`
- `DOMAIN`

## 3. Obtener SSL por primera vez
```bash
./infra/scripts/ssl-init.sh tudominio.com admin@tudominio.com
```

Este script:
- levanta Nginx en HTTP,
- solicita el certificado con Certbot webroot,
- recarga Nginx con TLS activo.

## 4. Primer deploy
```bash
./infra/scripts/deploy.sh
```

El script ejecuta:
1. `git pull`
2. build de la imagen `app`
3. `docker compose -f docker-compose.prod.yml up -d`
4. `alembic upgrade head`

## 5. Renovacion automatica SSL (cron)
Agrega una tarea cron para renovar y recargar Nginx:
```bash
crontab -e
```

Ejemplo (cada dia a las 03:30):
```cron
30 3 * * * cd /ruta/super-agent-platform && docker compose -f docker-compose.prod.yml run --rm --profile certbot certbot renew --webroot -w /var/www/certbot --quiet && docker compose -f docker-compose.prod.yml exec -T nginx nginx -s reload
```

## 6. Operacion diaria
- Ver logs en vivo de app y nginx:
```bash
./infra/scripts/logs.sh
```

- Crear backup de base de datos:
```bash
./infra/scripts/backup-db.sh
```

- Validar compose:
```bash
docker compose -f docker-compose.prod.yml config --quiet
```

- Reiniciar stack:
```bash
docker compose -f docker-compose.prod.yml restart
```

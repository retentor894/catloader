# CatLoader - Guia de Deployment en MiniPC Peladn WO4

## Resumen de Configuracion

Este documento describe la configuracion de CatLoader en el servidor MiniPC, coexistiendo con el proyecto Tuch sin interferencias.

## URLs de Acceso

| Ambiente | URL Publica | URL Local |
|----------|-------------|-----------|
| Production | https://catloader.nidourbano.net | http://localhost:8880 |
| Development | https://catloader-dev.nidourbano.net | http://localhost:2095 |

## Mapa de Puertos del Servidor

| Proyecto        | Servicio    | Puerto Host | Puerto Container | Cloudflare Compatible |
|-----------------|-------------|-------------|------------------|----------------------|
| Tuch Production | HTTP        | 80          | 80               | Si |
| Tuch Production | HTTPS       | 443         | 443              | Si |
| Tuch Production | PostgreSQL  | 5432        | 5432             | N/A |
| Tuch Development| HTTP        | 8080        | 80               | Si |
| Tuch Development| HTTPS       | 8443        | 443              | Si |
| Tuch Development| PostgreSQL  | 5433        | 5432             | N/A |
| **CatLoader Dev** | **HTTP**  | **2095**    | **80**           | **Si** |
| **CatLoader Prod**| **HTTP**  | **8880**    | **80**           | **Si** |

## Estructura de Directorios

```
/home/raptor/
├── tuch-production/app/        # Tuch Production (puertos 80, 443, 5432)
├── tuch-development/app/       # Tuch Development (puertos 8080, 8443, 5433)
├── catloader-production/app/   # CatLoader Production (puerto 8880)
└── catloader-development/app/  # CatLoader Development (puerto 2095)
```

## Contenedores Docker

### CatLoader Development
- **Proyecto Docker:** `catloader_dev`
- **Contenedores:**
  - `catloader-dev-backend` - API Python/FastAPI
  - `catloader-dev-frontend` - Nginx sirviendo frontend + proxy a API
- **Puerto:** 2095
- **URL local:** http://localhost:2095
- **URL publica:** https://catloader-dev.nidourbano.net

### CatLoader Production
- **Proyecto Docker:** `catloader_prod`
- **Contenedores:**
  - `catloader-prod-backend` - API Python/FastAPI
  - `catloader-prod-frontend` - Nginx sirviendo frontend + proxy a API
- **Puerto:** 8880
- **URL local:** http://localhost:8880
- **URL publica:** https://catloader.nidourbano.net

## Archivos de Configuracion

### Development (.env)
```bash
COMPOSE_PROJECT_NAME=catloader_dev
HTTP_PORT=2095
TEMP_DIR=/tmp/catloader-dev
```

### Production (.env)
```bash
COMPOSE_PROJECT_NAME=catloader_prod
HTTP_PORT=8880
TEMP_DIR=/tmp/catloader-prod
```

## Configuracion de Cloudflare

### Registros DNS

En Cloudflare Dashboard > nidourbano.net > DNS > Records:

| Tipo | Nombre | Contenido | Proxy | TTL |
|------|--------|-----------|-------|-----|
| A | catloader | 88.138.5.109 | Proxied | Auto |
| AAAA | catloader | 2a02:8440:658e:f51b:9bbc:b81e:9db2:39ed | Proxied | Auto |
| A | catloader-dev | 88.138.5.109 | Proxied | Auto |
| AAAA | catloader-dev | 2a02:8440:658e:f51b:9bbc:b81e:9db2:39ed | Proxied | Auto |

### Origin Rules (Puertos no estandar)

En Cloudflare Dashboard > nidourbano.net > Rules > Origin Rules:

**Regla 1: CatLoader Production Port**
- When: Hostname equals `catloader.nidourbano.net`
- Then: Destination Port > Rewrite to `8880`

**Regla 2: CatLoader Development Port**
- When: Hostname equals `catloader-dev.nidourbano.net`
- Then: Destination Port > Rewrite to `2095`

## Comandos de Gestion

### CatLoader Development
```bash
cd /home/raptor/catloader-development/app

# Iniciar
docker compose up -d

# Detener
docker compose down

# Ver logs
docker compose logs -f

# Reconstruir
docker compose build --no-cache
docker compose up -d
```

### CatLoader Production
```bash
cd /home/raptor/catloader-production/app

# Iniciar
docker compose up -d

# Detener
docker compose down

# Ver logs
docker compose logs -f

# Reconstruir
docker compose build --no-cache
docker compose up -d
```

### Ver todos los contenedores
```bash
docker ps --format "table {{.Names}}\t{{.Ports}}\t{{.Status}}"
```

## API Endpoints

| Endpoint | Metodo | Descripcion |
|----------|--------|-------------|
| `/` | GET | Frontend de la aplicacion |
| `/api/info` | POST | Obtener informacion y formatos de un video |
| `/api/download` | GET | Descargar video/audio |

### Ejemplo de uso
```bash
# Obtener info de un video (Development)
curl -X POST http://localhost:2095/api/info \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.youtube.com/watch?v=VIDEO_ID"}'

# Obtener info de un video (Production)
curl -X POST http://localhost:8880/api/info \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.youtube.com/watch?v=VIDEO_ID"}'

# Descargar video
curl "http://localhost:8880/api/download?url=VIDEO_URL&format_id=best" -o video.mp4
```

## Solucion de Problemas

### Error 403 en YouTube
Actualizar yt-dlp dentro del contenedor:
```bash
docker compose exec backend pip install -U yt-dlp
docker compose restart backend
```

### Verificar estado de servicios
```bash
# CatLoader Dev
curl http://localhost:2095/api/info -X POST -H "Content-Type: application/json" -d '{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'

# CatLoader Prod
curl http://localhost:8880/api/info -X POST -H "Content-Type: application/json" -d '{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
```

## Notas Importantes

1. **No interferir con Tuch:** Los puertos 80, 443, 5432 (prod) y 8080, 8443, 5433 (dev) estan reservados para Tuch.

2. **Puertos Cloudflare:** Los puertos 8880 y 2095 son compatibles con Cloudflare Proxy.

3. **Reinicio automatico:** Los contenedores tienen `restart: unless-stopped`, se reiniciaran automaticamente con el servidor.

4. **Logs rotados:** Los logs tienen limite de 10MB y 3 archivos para evitar llenar el disco.

5. **Directorios temporales:** Cada ambiente usa su propio directorio temporal para evitar conflictos.

## Arquitectura

```
                         [Usuario]
                             |
                             v
                      [Cloudflare CDN]
                             |
              +--------------+--------------+
              |                             |
   catloader.nidourbano.net     catloader-dev.nidourbano.net
              |                             |
              v                             v
         Puerto 8880                   Puerto 2095
              |                             |
              v                             v
    +-------------------+         +-------------------+
    | Nginx (Frontend)  |         | Nginx (Frontend)  |
    | catloader-prod-   |         | catloader-dev-    |
    | frontend          |         | frontend          |
    +-------------------+         +-------------------+
              |                             |
              v                             v
    +-------------------+         +-------------------+
    | FastAPI (API)     |         | FastAPI (API)     |
    | catloader-prod-   |         | catloader-dev-    |
    | backend           |         | backend           |
    +-------------------+         +-------------------+
              |                             |
              v                             v
       [yt-dlp + ffmpeg]           [yt-dlp + ffmpeg]
```

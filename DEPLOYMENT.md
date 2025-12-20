# CatLoader - Guia de Deployment en MiniPC Peladn WO4

## Resumen de Configuracion

Este documento describe la configuracion de CatLoader en el servidor MiniPC, coexistiendo con el proyecto Tuch sin interferencias.

## Mapa de Puertos del Servidor

| Proyecto        | Servicio    | Puerto Host | Puerto Container |
|-----------------|-------------|-------------|------------------|
| Tuch Production | HTTP        | 80          | 80               |
| Tuch Production | HTTPS       | 443         | 443              |
| Tuch Production | PostgreSQL  | 5432        | 5432             |
| Tuch Development| HTTP        | 8080        | 80               |
| Tuch Development| HTTPS       | 8443        | 443              |
| Tuch Development| PostgreSQL  | 5433        | 5432             |
| **CatLoader Dev** | **HTTP**  | **8180**    | **80**           |
| **CatLoader Prod**| **HTTP**  | **8280**    | **80**           |

## Estructura de Directorios

```
/home/raptor/
├── tuch-production/app/        # Tuch Production (puertos 80, 443, 5432)
├── tuch-development/app/       # Tuch Development (puertos 8080, 8443, 5433)
├── catloader-production/app/   # CatLoader Production (puerto 8280)
└── catloader-development/app/  # CatLoader Development (puerto 8180)
```

## Contenedores Docker

### CatLoader Development
- **Proyecto Docker:** `catloader_dev`
- **Contenedores:**
  - `catloader-dev-backend` - API Python/FastAPI
  - `catloader-dev-frontend` - Nginx sirviendo frontend + proxy a API
- **Puerto:** 8180
- **URL de acceso:** http://localhost:8180

### CatLoader Production
- **Proyecto Docker:** `catloader_prod`
- **Contenedores:**
  - `catloader-prod-backend` - API Python/FastAPI
  - `catloader-prod-frontend` - Nginx sirviendo frontend + proxy a API
- **Puerto:** 8280
- **URL de acceso:** http://localhost:8280

## Archivos de Configuracion

### Development (.env)
```bash
COMPOSE_PROJECT_NAME=catloader_dev
HTTP_PORT=8180
TEMP_DIR=/tmp/catloader-dev
```

### Production (.env)
```bash
COMPOSE_PROJECT_NAME=catloader_prod
HTTP_PORT=8280
TEMP_DIR=/tmp/catloader-prod
```

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
# Obtener info de un video
curl -X POST http://localhost:8180/api/info \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.youtube.com/watch?v=VIDEO_ID"}'

# Descargar video
curl "http://localhost:8180/api/download?url=VIDEO_URL&format_id=best" -o video.mp4
```

## Solucion de Problemas

### Error 403 en YouTube
Actualizar yt-dlp dentro del contenedor:
```bash
docker compose exec backend pip install -U yt-dlp
docker compose restart backend
```

### Contenedor unhealthy
El healthcheck requiere curl que no esta instalado por defecto. Esto no afecta el funcionamiento.

### Verificar estado de servicios
```bash
# CatLoader Dev
curl http://localhost:8180/api/info -X POST -H "Content-Type: application/json" -d '{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'

# CatLoader Prod
curl http://localhost:8280/api/info -X POST -H "Content-Type: application/json" -d '{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
```

## Notas Importantes

1. **No interferir con Tuch:** Los puertos 80, 443, 5432 (prod) y 8080, 8443, 5433 (dev) estan reservados para Tuch.

2. **Reinicio automatico:** Los contenedores tienen `restart: unless-stopped`, se reiniciaran automaticamente con el servidor.

3. **Logs rotados:** Los logs tienen limite de 10MB y 3 archivos para evitar llenar el disco.

4. **Directorios temporales:** Cada ambiente usa su propio directorio temporal para evitar conflictos.

## Arquitectura

```
                    [Usuario]
                        |
                        v
    +-------------------------------------------+
    |             Nginx (Frontend)              |
    |         catloader-{dev|prod}-frontend     |
    |              Puerto 8180/8280             |
    +-------------------------------------------+
           |                        |
           | Archivos estaticos     | /api/*
           v                        v
    [index.html, css, js]    +------------------+
                             |  FastAPI (API)   |
                             | catloader-backend|
                             |    Puerto 8000   |
                             +------------------+
                                     |
                                     v
                              [yt-dlp + ffmpeg]
                                     |
                                     v
                              [Video descargado]
```

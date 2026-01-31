#!/bin/bash
set -euo pipefail

# Script de Deploy para CatLoader
# Uso: ./scripts/deploy.sh
# Auto-detecta el ambiente (prod/dev) leyendo .env

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() {
    echo -e "${BLUE}[INFO] $1${NC}"
}

print_success() {
    echo -e "${GREEN}[OK] $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}[WARN] $1${NC}"
}

print_error() {
    echo -e "${RED}[ERROR] $1${NC}"
}

# Auto-detectar ambiente leyendo .env
ENV_FILE=".env"

if [[ ! -f "$ENV_FILE" ]]; then
    print_error "Archivo .env no encontrado"
    exit 1
fi

# Detectar ambiente basándose en COMPOSE_PROJECT_NAME
if grep -q "COMPOSE_PROJECT_NAME=catloader_prod" "$ENV_FILE" 2>/dev/null; then
    ENV="prod"
    BRANCH="main"
    ENV_LABEL="PRODUCCION"
    IS_PRODUCTION=true
    HTTP_PORT=8880
elif grep -q "COMPOSE_PROJECT_NAME=catloader_dev" "$ENV_FILE" 2>/dev/null; then
    ENV="dev"
    BRANCH="dev"
    ENV_LABEL="DESARROLLO"
    IS_PRODUCTION=false
    HTTP_PORT=2095
else
    print_error "No se pudo determinar el ambiente desde .env"
    print_error "Buscar COMPOSE_PROJECT_NAME=catloader_prod o catloader_dev"
    exit 1
fi

# Leer COMPOSE_PROJECT_NAME del .env
COMPOSE_PROJECT=$(grep '^COMPOSE_PROJECT_NAME=' "$ENV_FILE" 2>/dev/null | cut -d= -f2 | tr -d ' ')

print_info "Desplegando CatLoader en ambiente: $ENV_LABEL"

# Deployment lock to prevent concurrent deployments
LOCK_FILE="/tmp/catloader-deploy-${ENV}.lock"

acquire_lock() {
    if [[ -f "$LOCK_FILE" ]]; then
        LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
        if [[ -n "$LOCK_PID" ]] && kill -0 "$LOCK_PID" 2>/dev/null; then
            print_error "Deployment ya esta corriendo (PID: $LOCK_PID)"
            print_error "Si esto es un error, elimina el lock manualmente:"
            print_error "  rm -f $LOCK_FILE"
            exit 1
        else
            print_warning "Eliminando lock obsoleto de proceso muerto"
            rm -f "$LOCK_FILE"
        fi
    fi

    echo $$ > "$LOCK_FILE"
    print_success "Lock de deployment adquirido"
}

release_lock() {
    rm -f "$LOCK_FILE"
}

trap release_lock EXIT

acquire_lock

# Confirmación para producción (skip en modo automatizado)
if [[ "$IS_PRODUCTION" == "true" ]] && [[ "${AUTOMATED_DEPLOY:-}" != "true" ]]; then
    print_warning "Estas a punto de desplegar en PRODUCCION"
    read -p "Continuar? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Deploy cancelado"
        exit 0
    fi
fi

# Hacer pull del código
if [[ -d .git ]]; then
    print_info "Actualizando codigo desde repositorio..."
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
    print_info "Branch actual: $CURRENT_BRANCH"

    if [[ "$CURRENT_BRANCH" != "$BRANCH" ]]; then
        if [[ "$IS_PRODUCTION" == "true" ]]; then
            print_error "Produccion debe estar en la rama $BRANCH (actual: $CURRENT_BRANCH)"
            exit 1
        else
            print_warning "$ENV_LABEL deberia estar en la rama $BRANCH (actual: $CURRENT_BRANCH)"
        fi
    fi

    git pull origin "$BRANCH" || print_warning "No se pudo hacer pull (continuando de todos modos)"
fi

# Pre-deployment health checks
print_info "Verificando salud del sistema..."

# Check disk space (need at least 2GB free)
AVAILABLE_SPACE=$(df -BG . | tail -1 | awk '{print $4}' | sed 's/G//')
if [[ $AVAILABLE_SPACE -lt 2 ]]; then
    print_error "Espacio en disco insuficiente: ${AVAILABLE_SPACE}GB disponible (minimo: 2GB)"
    exit 1
fi
print_success "Espacio en disco: ${AVAILABLE_SPACE}GB disponible"

# Check if Docker is responsive
if ! docker ps >/dev/null 2>&1; then
    print_error "Docker no responde o no esta disponible"
    exit 1
fi
print_success "Docker respondiendo correctamente"

# Mostrar estado de contenedores antes
print_info "Estado actual de contenedores:"
docker compose -p "$COMPOSE_PROJECT" ps 2>/dev/null || echo "(no hay contenedores)"

# Build images
print_info "Construyendo imagenes..."
if ! docker compose -p "$COMPOSE_PROJECT" --env-file "$ENV_FILE" build; then
    print_error "Build fallo, manteniendo version anterior corriendo"
    exit 1
fi

print_info "Build exitoso, actualizando contenedores..."
if ! docker compose -p "$COMPOSE_PROJECT" --env-file "$ENV_FILE" up -d; then
    print_error "Error al iniciar contenedores"
    exit 1
fi

# Esperar a que los servicios estén listos
print_info "Esperando a que los servicios esten listos..."
sleep 5

# Smoke test - verify API is responding
print_info "Verificando que la API responde..."
MAX_RETRIES=20
RETRY_COUNT=0

while [[ $RETRY_COUNT -lt $MAX_RETRIES ]]; do
    # Test the info endpoint with a simple POST
    if curl -f -s -X POST "http://localhost:${HTTP_PORT}/api/info" \
        -H "Content-Type: application/json" \
        -d '{"url":"https://www.youtube.com/watch?v=test"}' > /dev/null 2>&1; then
        print_success "API respondiendo correctamente"
        break
    fi
    # Also try just reaching the frontend
    if curl -f -s "http://localhost:${HTTP_PORT}/" > /dev/null 2>&1; then
        print_success "Frontend respondiendo correctamente"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    sleep 2
done

if [[ $RETRY_COUNT -eq $MAX_RETRIES ]]; then
    print_warning "Servicios pueden no estar completamente listos"
    print_warning "Verifica manualmente: curl http://localhost:${HTTP_PORT}/"
fi

# Log deployment history (use parent of current directory)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_LOG="${REPO_ROOT}/../logs/deploy-history.log"
mkdir -p "$(dirname "$DEPLOY_LOG")"
CURRENT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
echo "$(date '+%Y-%m-%d %H:%M:%S') | $USER | $ENV_LABEL | $CURRENT_BRANCH | $CURRENT_COMMIT | SUCCESS" >> "$DEPLOY_LOG"

# Verificar estado
print_success "Deploy completado!"
print_success "Commit: $CURRENT_COMMIT ($CURRENT_BRANCH)"
echo ""
print_info "Estado de servicios:"
docker compose -p "$COMPOSE_PROJECT" ps

echo ""
print_info "Comandos utiles:"
echo "  Ver logs:        docker compose -p $COMPOSE_PROJECT logs -f"
echo "  Ver logs API:    docker compose -p $COMPOSE_PROJECT logs -f backend"
echo "  Ver logs Web:    docker compose -p $COMPOSE_PROJECT logs -f frontend"
echo "  Estado:          docker compose -p $COMPOSE_PROJECT ps"
echo "  Detener:         docker compose -p $COMPOSE_PROJECT down"
echo "  Reiniciar:       docker compose -p $COMPOSE_PROJECT restart"

echo ""
if [[ "$IS_PRODUCTION" == "true" ]]; then
    print_success "Produccion disponible en: https://catloader.nidourbano.net"
else
    print_success "Desarrollo disponible en: https://catloader-dev.nidourbano.net"
fi

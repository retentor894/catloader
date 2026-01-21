import os
import shutil
import logging
import tempfile
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp
from .routes import download
from .utils import metrics
from .models.schemas import HealthResponse, HealthDetailedResponse

logger = logging.getLogger(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - startup and shutdown events."""
    # Startup
    logger.info("CatLoader API starting up")
    yield
    # Shutdown - cleanup thread pool executor
    logger.info("CatLoader API shutting down - cleaning up resources")
    download.shutdown_executor(wait=False)
    logger.info("Thread pool executor shutdown complete")


app = FastAPI(
    title="CatLoader",
    description="Video downloader API supporting 1000+ sites",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS from environment variable
# CORS_ORIGINS can be a comma-separated list of allowed origins, or "*" for all
# Default to localhost origins for development
cors_origins_env = os.getenv("CORS_ORIGINS", "http://localhost:5500,http://localhost:8080,http://127.0.0.1:5500")
allow_all_origins = cors_origins_env.strip() == "*"

# Compute CORS settings based on configuration
# Note: credentials cannot be used with wildcard origin per CORS spec
cors_origins = ["*"] if allow_all_origins else [
    origin.strip() for origin in cors_origins_env.split(",") if origin.strip()
]
cors_credentials = not allow_all_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_credentials,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Include routers
app.include_router(download.router)


@app.get("/")
async def root():
    return {"message": "CatLoader API", "status": "running"}


@app.get("/health", response_model=HealthResponse)
async def health():
    """
    Health check endpoint with system status.

    Returns basic health for load balancers, with optional detailed info.
    """
    return HealthResponse(status="healthy")


@app.get("/health/detailed", response_model=HealthDetailedResponse)
async def health_detailed():
    """
    Detailed health check with system metrics.

    Includes thread pool status, disk space, and metrics.
    Use for debugging and monitoring dashboards.

    SECURITY WARNING: This endpoint exposes operational details (thread pool
    stats, disk usage, yt-dlp version, error counts) that could aid attackers
    in timing attacks or identifying vulnerabilities. In production deployments:

    1. Restrict access to internal networks only via reverse proxy:
       location /health/detailed {
           allow 10.0.0.0/8;
           allow 172.16.0.0/12;
           allow 192.168.0.0/16;
           deny all;
           proxy_pass http://backend:8000;
       }

    2. Or require authentication for this endpoint.

    The basic /health endpoint is safe for public access (load balancer checks).
    """
    # Thread pool status (using public API to avoid coupling)
    thread_pool_status = download.get_executor_stats()

    # Disk space for temp directory
    temp_dir = tempfile.gettempdir()
    try:
        disk_usage = shutil.disk_usage(temp_dir)
        # Guard against division by zero (possible on some virtual filesystems)
        used_percent = (
            round((disk_usage.used / disk_usage.total) * 100, 1)
            if disk_usage.total > 0
            else 0.0
        )
        disk_status = {
            "temp_dir": temp_dir,
            "total_gb": round(disk_usage.total / (1024**3), 2),
            "free_gb": round(disk_usage.free / (1024**3), 2),
            "used_percent": used_percent,
        }
    except OSError:
        disk_status = {"error": "Unable to check disk space"}

    # Application metrics
    metrics_stats = metrics.get_stats()

    # yt-dlp info
    try:
        ytdlp_info = {
            "version": yt_dlp.version.__version__,
            "status": "available",
        }
    except Exception:
        ytdlp_info = {"status": "unavailable"}

    return HealthDetailedResponse(
        status="healthy",
        thread_pool=thread_pool_status,
        disk=disk_status,
        metrics=metrics_stats,
        yt_dlp=ytdlp_info,
    )

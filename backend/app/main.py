import os
import shutil
import logging
import tempfile
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import download
from .utils import metrics

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
    download._executor.shutdown(wait=False)
    logger.info("Thread pool executor shutdown complete")


app = FastAPI(
    title="CatLoader",
    description="Video downloader API supporting 1000+ sites",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS from environment variable
# CORS_ORIGINS can be a comma-separated list of allowed origins
# Default to localhost origins for development
cors_origins_env = os.getenv("CORS_ORIGINS", "http://localhost:5500,http://localhost:8080,http://127.0.0.1:5500")
allow_all_origins = cors_origins_env.strip() == "*"

if allow_all_origins:
    # Allow all origins (not recommended for production with credentials)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,  # Cannot use credentials with wildcard origin
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
else:
    # Parse comma-separated origins
    cors_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

# Include routers
app.include_router(download.router)


@app.get("/")
async def root():
    return {"message": "CatLoader API", "status": "running"}


@app.get("/health")
async def health():
    """
    Health check endpoint with system status.

    Returns basic health for load balancers, with optional detailed info.
    """
    return {"status": "healthy"}


@app.get("/health/detailed")
async def health_detailed():
    """
    Detailed health check with system metrics.

    Includes thread pool status, disk space, and metrics.
    Use for debugging and monitoring dashboards.
    """
    # Thread pool status
    # Note: Accessing private attributes (_max_workers, _threads) for monitoring.
    # These are implementation details of ThreadPoolExecutor and may change in future Python versions.
    executor = download._executor
    try:
        thread_pool_status = {
            "max_workers": executor._max_workers,
            "active_threads": len(executor._threads),
        }
    except AttributeError:
        # Fallback if private attributes change in future Python versions
        thread_pool_status = {
            "status": "monitoring unavailable",
        }

    # Disk space for temp directory
    temp_dir = tempfile.gettempdir()
    try:
        disk_usage = shutil.disk_usage(temp_dir)
        disk_status = {
            "temp_dir": temp_dir,
            "total_gb": round(disk_usage.total / (1024**3), 2),
            "free_gb": round(disk_usage.free / (1024**3), 2),
            "used_percent": round((disk_usage.used / disk_usage.total) * 100, 1),
        }
    except OSError:
        disk_status = {"error": "Unable to check disk space"}

    # Application metrics
    metrics_stats = metrics.get_stats()

    return {
        "status": "healthy",
        "thread_pool": thread_pool_status,
        "disk": disk_status,
        "metrics": metrics_stats,
    }

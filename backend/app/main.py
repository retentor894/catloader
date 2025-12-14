import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import download

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

app = FastAPI(
    title="CatLoader",
    description="Video downloader API supporting 1000+ sites",
    version="1.0.0"
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
    return {"status": "healthy"}

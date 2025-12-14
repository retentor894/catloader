from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import download

app = FastAPI(
    title="CatLoader",
    description="Video downloader API supporting 1000+ sites",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
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

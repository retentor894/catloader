from pydantic import BaseModel, field_validator
from typing import Optional, List

from ..validation import validate_url as config_validate_url


class URLRequest(BaseModel):
    url: str

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate that the URL is properly formatted."""
        return config_validate_url(v)


class VideoFormat(BaseModel):
    format_id: str
    ext: str
    resolution: Optional[str] = None
    filesize: Optional[int] = None
    filesize_approx: Optional[int] = None
    has_audio: bool = True
    has_video: bool = True
    quality_label: Optional[str] = None


class VideoInfo(BaseModel):
    title: str
    thumbnail: Optional[str] = None
    duration: Optional[int] = None
    uploader: Optional[str] = None
    video_formats: List[VideoFormat] = []
    audio_formats: List[VideoFormat] = []


class ErrorResponse(BaseModel):
    """Error response schema matching FastAPI's HTTPException format."""
    detail: str


# =============================================================================
# Health Check Response Models
# =============================================================================

class ThreadPoolStatus(BaseModel):
    """Thread pool executor status."""
    max_workers: Optional[int] = None
    active_threads: Optional[int] = None
    status: Optional[str] = None  # "monitoring unavailable" fallback


class DiskStatus(BaseModel):
    """Disk space status for temp directory."""
    temp_dir: Optional[str] = None
    total_gb: Optional[float] = None
    free_gb: Optional[float] = None
    used_percent: Optional[float] = None
    error: Optional[str] = None  # Set when disk check fails


class MetricsStatus(BaseModel):
    """Application metrics counters."""
    timeouts: int = 0
    retries: int = 0
    successes: int = 0
    errors: int = 0


class YtdlpStatus(BaseModel):
    """yt-dlp availability status."""
    version: Optional[str] = None
    status: str  # "available" or "unavailable"


class HealthResponse(BaseModel):
    """Simple health check response."""
    status: str


class HealthDetailedResponse(BaseModel):
    """Detailed health check response with system metrics."""
    status: str
    thread_pool: ThreadPoolStatus
    disk: DiskStatus
    metrics: MetricsStatus
    yt_dlp: YtdlpStatus

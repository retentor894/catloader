from pydantic import BaseModel, field_validator
from typing import Optional, List

from ..config import validate_url as config_validate_url


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


class DownloadRequest(BaseModel):
    url: str
    format_id: str
    audio_only: bool = False


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None

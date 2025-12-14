from pydantic import BaseModel, field_validator
from typing import Optional, List
import re


class URLRequest(BaseModel):
    url: str

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate that the URL is properly formatted."""
        if not v or not v.strip():
            raise ValueError("URL cannot be empty")

        v = v.strip()

        # Basic URL pattern - must start with http:// or https://
        url_pattern = re.compile(
            r'^https?://'  # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,}|'  # domain
            r'localhost|'  # or localhost
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # or IPv4
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?]\S+)$',  # path
            re.IGNORECASE
        )

        if not url_pattern.match(v):
            raise ValueError("Invalid URL format. URL must start with http:// or https://")

        return v


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

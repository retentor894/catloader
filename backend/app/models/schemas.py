from pydantic import BaseModel
from typing import Optional, List


class URLRequest(BaseModel):
    url: str


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

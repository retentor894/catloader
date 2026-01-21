import asyncio
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..models.schemas import URLRequest, VideoInfo, ErrorResponse
from ..services.downloader import (
    get_video_info,
    download_video,
    download_video_with_progress,
    remove_completed_download,
    cleanup_temp_dir,
    CHUNK_SIZE,
)
from ..exceptions import VideoExtractionError, DownloadError, NetworkError, CatLoaderError

logger = logging.getLogger(__name__)

# Timeout for video info extraction (seconds)
INFO_EXTRACTION_TIMEOUT = 90

# URL validation pattern
URL_PATTERN = re.compile(
    r'^https?://'
    r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,}|'
    r'localhost|'
    r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
    r'(?::\d+)?'
    r'(?:/?|[/?]\S+)$',
    re.IGNORECASE
)


def validate_url(url: str) -> str:
    """Validate URL format and return cleaned URL."""
    if not url or not url.strip():
        raise HTTPException(status_code=400, detail="URL cannot be empty")

    url = url.strip()
    if not URL_PATTERN.match(url):
        raise HTTPException(status_code=400, detail="Invalid URL format")

    return url


def sanitize_filename(filename: str) -> str:
    """Sanitize filename for Content-Disposition header (RFC 5987 compliant)."""
    # Remove problematic characters
    safe_filename = filename.replace('"', "'").replace('\n', '').replace('\r', '')
    # Encode for ASCII fallback
    ascii_filename = safe_filename.encode('ascii', 'ignore').decode('ascii')
    # URL-encode for UTF-8 filename*
    encoded_filename = quote(filename)
    return ascii_filename, encoded_filename

router = APIRouter(prefix="/api", tags=["download"])

# Thread pool for blocking operations
_executor = ThreadPoolExecutor(max_workers=4)


async def run_in_executor(func, *args, **kwargs):
    """Run a blocking function in thread pool."""
    loop = asyncio.get_event_loop()
    if kwargs:
        func = partial(func, **kwargs)
    return await loop.run_in_executor(_executor, func, *args)


@router.post("/info", response_model=VideoInfo, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}, 504: {"model": ErrorResponse}})
async def get_info(request: URLRequest):
    """Get video information and available formats."""
    try:
        info = await asyncio.wait_for(
            run_in_executor(get_video_info, request.url),
            timeout=INFO_EXTRACTION_TIMEOUT
        )
        return info
    except asyncio.TimeoutError:
        logger.warning(f"Timeout extracting info for {request.url}")
        raise HTTPException(
            status_code=504,
            detail="Video info extraction timed out. The video may be too long or the server is busy. Please try again."
        )
    except VideoExtractionError as e:
        # Client error - invalid/unsupported URL
        raise HTTPException(status_code=400, detail=str(e))
    except NetworkError as e:
        # Server/network error
        raise HTTPException(status_code=503, detail=str(e))
    except CatLoaderError as e:
        # Other application errors
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # Unexpected errors - 500
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/download", responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def download(
    url: str = Query(..., description="Video URL"),
    format_id: str = Query("best", description="Format ID to download"),
    audio_only: bool = Query(False, description="Download audio only")
):
    """Download video or audio file."""
    try:
        # FastAPI already decodes query params - don't double-decode
        validated_url = validate_url(url)
        filename, content_type, file_size, file_stream = await run_in_executor(
            download_video, validated_url, format_id, audio_only
        )

        # Sanitize filename for Content-Disposition header (RFC 5987)
        ascii_filename, encoded_filename = sanitize_filename(filename)
        if not ascii_filename:
            ascii_filename = "download" + (".mp3" if audio_only else ".mp4")
            encoded_filename = ascii_filename

        return StreamingResponse(
            file_stream,
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{encoded_filename}',
                "Content-Length": str(file_size),
                "Cache-Control": "no-cache",
            }
        )
    except DownloadError as e:
        # Client error - download failed
        raise HTTPException(status_code=400, detail=str(e))
    except NetworkError as e:
        # Server/network error
        raise HTTPException(status_code=503, detail=str(e))
    except CatLoaderError as e:
        # Other application errors
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # Unexpected errors - 500
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/download/progress")
async def download_progress(
    url: str = Query(..., description="Video URL"),
    format_id: str = Query("best", description="Format ID to download"),
    audio_only: bool = Query(False, description="Download audio only")
):
    """Stream download progress via Server-Sent Events."""
    # FastAPI already decodes query params - don't double-decode
    validated_url = validate_url(url)

    def event_generator():
        try:
            yield from download_video_with_progress(validated_url, format_id, audio_only)
        except Exception as e:
            logger.exception(f"Error in download progress stream: {e}")
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/download/file/{download_id}")
async def download_file(download_id: str):
    """Download a completed file by its ID."""
    file_info = remove_completed_download(download_id)

    if not file_info:
        raise HTTPException(status_code=404, detail="Download not found or expired")

    file_path = file_info.get('file_path')
    temp_dir = file_info.get('temp_dir')

    if not file_path or not temp_dir:
        if temp_dir:
            cleanup_temp_dir(temp_dir)
        raise HTTPException(status_code=404, detail="Invalid download state")

    # Validate file is within temp directory (prevent path traversal)
    try:
        real_file_path = os.path.realpath(file_path)
        real_temp_dir = os.path.realpath(temp_dir)
        if not real_file_path.startswith(real_temp_dir + os.sep):
            logger.error(f"Path traversal attempt detected: {file_path}")
            cleanup_temp_dir(temp_dir)
            raise HTTPException(status_code=400, detail="Invalid file path")
    except OSError:
        cleanup_temp_dir(temp_dir)
        raise HTTPException(status_code=404, detail="File not found")

    # Sanitize filename for header
    ascii_filename, encoded_filename = sanitize_filename(file_info.get('filename', 'download'))
    if not ascii_filename:
        ascii_filename = 'download'
        encoded_filename = 'download'

    def file_generator():
        try:
            with open(file_path, 'rb') as f:
                while chunk := f.read(CHUNK_SIZE):
                    yield chunk
        except FileNotFoundError:
            # Handle TOCTOU race - file was deleted between check and open
            logger.warning(f"File disappeared during streaming: {file_path}")
        except Exception as e:
            logger.error(f"Error streaming file: {e}")
        finally:
            cleanup_temp_dir(temp_dir)

    return StreamingResponse(
        file_generator(),
        media_type=file_info.get('content_type', 'application/octet-stream'),
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{encoded_filename}',
            "Content-Length": str(file_info.get('file_size', 0)),
            "Cache-Control": "no-cache",
        }
    )

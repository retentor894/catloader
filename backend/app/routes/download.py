import asyncio
import json
import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from urllib.parse import quote
from typing import TypeVar, Callable, Tuple

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
from ..exceptions import VideoExtractionError, DownloadError, NetworkError, CatLoaderError, FileSizeLimitError
from ..config import (
    INFO_EXTRACTION_TIMEOUT,
    DOWNLOAD_INIT_TIMEOUT,
    SSE_STREAM_TIMEOUT,
    THREAD_POOL_MAX_WORKERS,
    MAX_CONCURRENT_OPERATIONS,
)
from ..validation import validate_url as config_validate_url, validate_format_id
from ..utils import metrics

logger = logging.getLogger(__name__)

T = TypeVar('T')


def validate_url_for_http(url: str) -> str:
    """
    Validate URL and convert ValueError to HTTPException.

    This is a thin wrapper around config.validate_url that converts
    ValueError exceptions to HTTPException for use in HTTP handlers.
    """
    try:
        return config_validate_url(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def validate_format_id_for_http(format_id: str) -> str:
    """
    Validate format_id and convert ValueError to HTTPException.

    This validates yt-dlp format strings to prevent injection of
    unexpected characters.
    """
    try:
        return validate_format_id(format_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def sanitize_filename(filename: str) -> Tuple[str, str]:
    """
    Sanitize filename for Content-Disposition header (RFC 5987 compliant).

    Returns:
        Tuple of (ascii_filename, encoded_filename) for use in Content-Disposition header.
    """
    # Remove problematic characters
    safe_filename = filename.replace('"', "'").replace('\n', '').replace('\r', '')
    # Encode for ASCII fallback
    ascii_filename = safe_filename.encode('ascii', 'ignore').decode('ascii')
    # URL-encode for UTF-8 filename*
    encoded_filename = quote(filename)
    return ascii_filename, encoded_filename

router = APIRouter(prefix="/api", tags=["download"])

# Thread pool for blocking operations
# Note: Using more workers to handle orphaned threads from timeouts
_executor = ThreadPoolExecutor(max_workers=THREAD_POOL_MAX_WORKERS)

# Semaphore to limit concurrent yt-dlp operations
# This prevents thread pool exhaustion when many timeouts occur
# (orphaned threads from timeouts continue running until yt-dlp's socket_timeout)
_operations_semaphore = asyncio.Semaphore(MAX_CONCURRENT_OPERATIONS)


def _generate_request_id() -> str:
    """Generate a short request ID for logging correlation."""
    return uuid.uuid4().hex[:8]


class ServerAtCapacityError(Exception):
    """Raised when the server cannot accept more concurrent operations."""
    pass


async def run_with_timeout(
    func: Callable[..., T],
    timeout: float,
    *args,
    **kwargs
) -> T:
    """
    Run a blocking function with timeout handling and concurrency limiting.

    Uses a semaphore to limit concurrent operations and prevent thread pool
    exhaustion when many timeouts occur.

    IMPORTANT: When timeout occurs, the underlying thread continues running until
    yt-dlp completes (limited by its socket_timeout). This is a known limitation
    because yt-dlp doesn't support cooperative cancellation. The thread will be
    orphaned but will eventually terminate due to yt-dlp's internal timeouts.

    Args:
        func: The blocking function to execute
        timeout: Timeout in seconds
        *args, **kwargs: Arguments to pass to the function

    Returns:
        The function's return value

    Raises:
        asyncio.TimeoutError: If the function doesn't complete within timeout
        ServerAtCapacityError: If max concurrent operations limit is reached
    """
    # Try to acquire semaphore with minimal wait
    # If server is at capacity, fail fast instead of queueing
    try:
        await asyncio.wait_for(_operations_semaphore.acquire(), timeout=0.1)
    except asyncio.TimeoutError:
        raise ServerAtCapacityError(
            f"Server at capacity ({MAX_CONCURRENT_OPERATIONS} concurrent operations). "
            "Please try again later."
        )

    loop = asyncio.get_running_loop()

    if kwargs:
        func = partial(func, **kwargs)

    try:
        # Run directly in our executor with timeout
        # Using a single executor avoids the race condition of having
        # future.result() block in a separate thread pool
        return await asyncio.wait_for(
            loop.run_in_executor(_executor, func, *args),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        # The thread continues running until yt-dlp's socket_timeout kicks in
        # We can't cancel it, but it will eventually terminate
        logger.warning(
            f"Timeout after {timeout}s - thread will continue until yt-dlp's "
            f"internal timeout (orphaned thread)"
        )
        raise
    finally:
        _operations_semaphore.release()


@router.post("/info", response_model=VideoInfo, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}, 504: {"model": ErrorResponse}})
async def get_info(request: URLRequest):
    """Get video information and available formats."""
    request_id = _generate_request_id()
    start_time = time.monotonic()

    logger.info(f"[{request_id}] Starting info extraction for: {request.url}")

    try:
        # Note: No retry at endpoint level to avoid multiplying timeout
        # yt-dlp has internal retry logic (retries=3 in COMMON_OPTS)
        info = await run_with_timeout(
            get_video_info,
            INFO_EXTRACTION_TIMEOUT,
            request.url
        )
        elapsed = time.monotonic() - start_time
        logger.info(f"[{request_id}] Info extraction completed in {elapsed:.2f}s")
        return info
    except ServerAtCapacityError as e:
        elapsed = time.monotonic() - start_time
        logger.warning(f"[{request_id}] Server at capacity after {elapsed:.2f}s")
        raise HTTPException(status_code=503, detail=str(e))
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - start_time
        metrics.record_timeout(endpoint="/api/info", elapsed=elapsed)
        logger.warning(
            f"[{request_id}] Timeout after {elapsed:.2f}s (limit: {INFO_EXTRACTION_TIMEOUT}s) "
            f"extracting info for {request.url}. "
            f"Note: Background thread may continue until yt-dlp's socket_timeout."
        )
        raise HTTPException(
            status_code=504,
            detail="Server timeout. The video may be too long or the server is busy. Please try again."
        )
    except VideoExtractionError as e:
        elapsed = time.monotonic() - start_time
        metrics.record_error(operation="info_extraction", error=str(e)[:100], elapsed=elapsed)
        logger.warning(f"[{request_id}] Extraction error after {elapsed:.2f}s: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except NetworkError as e:
        elapsed = time.monotonic() - start_time
        metrics.record_error(operation="info_extraction", error=str(e)[:100], elapsed=elapsed)
        logger.warning(f"[{request_id}] Network error after {elapsed:.2f}s: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except CatLoaderError as e:
        elapsed = time.monotonic() - start_time
        metrics.record_error(operation="info_extraction", error=str(e)[:100], elapsed=elapsed)
        logger.warning(f"[{request_id}] Application error after {elapsed:.2f}s: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        elapsed = time.monotonic() - start_time
        metrics.record_error(operation="info_extraction", error=str(e)[:100], elapsed=elapsed)
        logger.exception(f"[{request_id}] Unexpected error after {elapsed:.2f}s: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/download", responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}, 504: {"model": ErrorResponse}})
async def download(
    url: str = Query(..., description="Video URL"),
    format_id: str = Query("best", description="Format ID to download"),
    audio_only: bool = Query(False, description="Download audio only")
):
    """Download video or audio file."""
    request_id = _generate_request_id()
    start_time = time.monotonic()

    # Validate inputs
    validated_url = validate_url_for_http(url)
    validated_format_id = validate_format_id_for_http(format_id)

    logger.info(f"[{request_id}] Starting download for: {validated_url} (format={validated_format_id}, audio_only={audio_only})")

    file_stream = None
    try:
        # Note: No retry at endpoint level to avoid multiplying timeout
        # yt-dlp has internal retry logic (retries=3 in COMMON_OPTS)
        filename, content_type, file_size, file_stream = await run_with_timeout(
            download_video,
            DOWNLOAD_INIT_TIMEOUT,
            validated_url, validated_format_id, audio_only
        )

        elapsed = time.monotonic() - start_time
        logger.info(f"[{request_id}] Download ready in {elapsed:.2f}s: {filename} ({file_size} bytes)")

        # Sanitize filename for Content-Disposition header (RFC 5987)
        ascii_filename, encoded_filename = sanitize_filename(filename)
        if not ascii_filename:
            ascii_filename = "download" + (".mp3" if audio_only else ".mp4")
            encoded_filename = ascii_filename

        # Transfer ownership of file_stream to StreamingResponse
        # Set to None so we don't close it in the except block
        response_stream = file_stream
        file_stream = None

        return StreamingResponse(
            response_stream,
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{encoded_filename}',
                "Content-Length": str(file_size),
                "Cache-Control": "no-cache",
            }
        )
    except ServerAtCapacityError as e:
        elapsed = time.monotonic() - start_time
        logger.warning(f"[{request_id}] Server at capacity after {elapsed:.2f}s")
        raise HTTPException(status_code=503, detail=str(e))
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - start_time
        metrics.record_timeout(endpoint="/api/download", elapsed=elapsed)
        logger.warning(
            f"[{request_id}] Timeout after {elapsed:.2f}s (limit: {DOWNLOAD_INIT_TIMEOUT}s) "
            f"downloading {validated_url}. "
            f"Note: Background thread may continue until yt-dlp's socket_timeout."
        )
        raise HTTPException(
            status_code=504,
            detail="Server timeout. The video may be too long or the server is busy. Please try again."
        )
    except FileSizeLimitError as e:
        elapsed = time.monotonic() - start_time
        metrics.record_error(operation="download", error=str(e)[:100], elapsed=elapsed)
        logger.warning(f"[{request_id}] File size limit exceeded after {elapsed:.2f}s: {e}")
        raise HTTPException(status_code=413, detail=str(e))
    except DownloadError as e:
        elapsed = time.monotonic() - start_time
        metrics.record_error(operation="download", error=str(e)[:100], elapsed=elapsed)
        logger.warning(f"[{request_id}] Download error after {elapsed:.2f}s: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except NetworkError as e:
        elapsed = time.monotonic() - start_time
        metrics.record_error(operation="download", error=str(e)[:100], elapsed=elapsed)
        logger.warning(f"[{request_id}] Network error after {elapsed:.2f}s: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except CatLoaderError as e:
        elapsed = time.monotonic() - start_time
        metrics.record_error(operation="download", error=str(e)[:100], elapsed=elapsed)
        logger.warning(f"[{request_id}] Application error after {elapsed:.2f}s: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        elapsed = time.monotonic() - start_time
        metrics.record_error(operation="download", error=str(e)[:100], elapsed=elapsed)
        logger.exception(f"[{request_id}] Unexpected error after {elapsed:.2f}s: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
    finally:
        # If file_stream was not transferred to StreamingResponse, consume it to trigger cleanup
        if file_stream is not None:
            try:
                # Consuming the generator triggers its finally block which cleans up temp files
                for _ in file_stream:
                    pass
            except Exception as cleanup_error:
                # Best effort cleanup - log but don't raise since we're already in error handling
                logger.debug(f"Error during file stream cleanup: {cleanup_error}")


@router.get("/download/progress")
async def download_progress(
    url: str = Query(..., description="Video URL"),
    format_id: str = Query("best", description="Format ID to download"),
    audio_only: bool = Query(False, description="Download audio only")
):
    """Stream download progress via Server-Sent Events."""
    # Validate inputs
    validated_url = validate_url_for_http(url)
    validated_format_id = validate_format_id_for_http(format_id)

    def event_generator():
        start_time = time.monotonic()
        try:
            for event in download_video_with_progress(validated_url, validated_format_id, audio_only):
                # Check if connection has exceeded maximum allowed time
                elapsed = time.monotonic() - start_time
                if elapsed > SSE_STREAM_TIMEOUT:
                    logger.warning(f"SSE stream timeout after {elapsed:.0f}s for {validated_url}")
                    yield f"data: {json.dumps({'status': 'error', 'message': 'Connection timeout'})}\n\n"
                    return
                yield event
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

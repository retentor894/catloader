import asyncio
import json
import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from urllib.parse import quote
from typing import TypeVar, Callable, Tuple, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..models.schemas import URLRequest, VideoInfo, ErrorResponse


class SemaphoreGuardedIterator:
    """
    Wrapper that guarantees semaphore release when iteration ends.

    This solves a race condition where if a client disconnects before the
    generator starts iterating, the generator's finally block never executes.
    This wrapper ensures release() is called when close() is invoked by
    Starlette, even if iteration never started.
    """

    def __init__(self, generator, semaphore: asyncio.Semaphore):
        self._generator = generator
        self._semaphore = semaphore
        self._released = False

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return next(self._generator)
        except StopIteration:
            self._release()
            raise

    def close(self):
        """Called by Starlette when response ends or client disconnects."""
        self._release()
        if hasattr(self._generator, 'close'):
            self._generator.close()

    def _release(self):
        if not self._released:
            self._released = True
            self._semaphore.release()


from ..services.downloader import (
    get_video_info,
    download_video,
    download_video_with_progress,
    remove_completed_download,
    cleanup_temp_dir,
)
from ..exceptions import VideoExtractionError, DownloadError, NetworkError, CatLoaderError, FileSizeLimitError
from ..config import (
    INFO_EXTRACTION_TIMEOUT,
    DOWNLOAD_INIT_TIMEOUT,
    SSE_STREAM_TIMEOUT,
    THREAD_POOL_MAX_WORKERS,
    MAX_CONCURRENT_OPERATIONS,
    CHUNK_SIZE,
)
from ..validation import validate_url as config_validate_url, validate_format_id, validate_download_id
from ..utils import metrics

logger = logging.getLogger(__name__)

T = TypeVar('T')

# Maximum length for error messages in metrics (prevents log bloat)
_METRICS_ERROR_MAX_LENGTH = 100


def _truncate_error(error: str, max_length: int = _METRICS_ERROR_MAX_LENGTH) -> str:
    """Truncate error message with indication if truncated."""
    if len(error) <= max_length:
        return error
    # Leave room for "..." suffix
    return error[:max_length - 3] + "..."


def _sanitize_for_log(value: str, max_length: int = 200) -> str:
    """
    Sanitize user-controlled data for safe logging.

    Prevents log injection attacks by removing/escaping:
    - Newlines (could create fake log entries)
    - Carriage returns (same)
    - ANSI escape codes (could corrupt terminals/log viewers)

    Args:
        value: User-controlled string to sanitize
        max_length: Maximum length to prevent log bloat

    Returns:
        Sanitized string safe for logging
    """
    # Remove newlines and carriage returns
    sanitized = value.replace('\n', '\\n').replace('\r', '\\r')
    # Remove ANSI escape sequences (CSI sequences start with ESC[)
    sanitized = sanitized.replace('\x1b', '\\x1b')
    # Truncate if too long
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length - 3] + "..."
    return sanitized


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


def validate_download_id_for_http(download_id: str) -> str:
    """
    Validate download_id and convert ValueError to HTTPException.

    This validates download IDs to ensure they match the expected format
    (URL-safe base64 from secrets.token_urlsafe).
    """
    try:
        return validate_download_id(download_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def sanitize_filename(filename: str) -> Tuple[str, str]:
    """
    Sanitize filename for Content-Disposition header (RFC 5987 compliant).

    This function prepares filenames for HTTP Content-Disposition headers by
    providing both an ASCII fallback and a UTF-8 encoded version. This ensures
    compatibility with both old browsers (ASCII) and modern browsers (UTF-8).

    Args:
        filename: The original filename, may contain Unicode characters.

    Returns:
        Tuple of (ascii_filename, encoded_filename):
        - ascii_filename: ASCII-safe version with non-ASCII chars removed
        - encoded_filename: URL-encoded UTF-8 version for filename* parameter

    Examples:
        >>> sanitize_filename("video.mp4")
        ('video.mp4', 'video.mp4')

        >>> sanitize_filename("日本語動画.mp4")
        ('', '%E6%97%A5%E6%9C%AC%E8%AA%9E%E5%8B%95%E7%94%BB.mp4')

        >>> sanitize_filename('video "test".mp4')
        ("video 'test'.mp4", "video%20%22test%22.mp4")

    Usage in Content-Disposition header:
        Content-Disposition: attachment; filename="video.mp4"; filename*=UTF-8''video.mp4
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
#
# NOTE: We use lazy initialization to avoid event loop binding issues in Python < 3.10.
# In Python < 3.10, creating asyncio.Semaphore at module level could bind it to a
# different event loop than the one FastAPI uses.
_operations_semaphore: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    """Get or create the operations semaphore (lazy initialization)."""
    global _operations_semaphore
    if _operations_semaphore is None:
        _operations_semaphore = asyncio.Semaphore(MAX_CONCURRENT_OPERATIONS)
    return _operations_semaphore


# =============================================================================
# Public API for executor management (used by main.py)
# =============================================================================

def get_executor_stats() -> dict:
    """
    Get thread pool executor statistics for monitoring.

    WARNING: This function accesses private attributes of ThreadPoolExecutor
    (_max_workers, _threads) which are implementation details that may change
    in future Python versions.

    Why we do this:
    - ThreadPoolExecutor provides no public API for monitoring
    - These stats are valuable for health checks and debugging
    - The fallback ensures graceful degradation if attributes change

    Tested on: Python 3.9, 3.10, 3.11, 3.12

    Alternatives considered:
    - Custom executor wrapper: Adds complexity for minimal benefit
    - External monitoring (prometheus): Overkill for this use case
    - No monitoring: Reduces observability for debugging timeouts

    Returns:
        Dictionary with executor stats, or error status if unavailable.
    """
    try:
        return {
            "max_workers": _executor._max_workers,
            "active_threads": len(_executor._threads),
        }
    except AttributeError:
        # Fallback if private attributes change in future Python versions
        return {"status": "monitoring unavailable"}


def shutdown_executor(wait: bool = False) -> None:
    """
    Shutdown the thread pool executor.

    Args:
        wait: If True, wait for all pending futures to complete.
    """
    _executor.shutdown(wait=wait)


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
    semaphore = _get_semaphore()
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=0.1)
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
        semaphore.release()


@router.post("/info", response_model=VideoInfo, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}, 504: {"model": ErrorResponse}})
async def get_info(request: URLRequest):
    """Get video information and available formats."""
    request_id = _generate_request_id()
    start_time = time.monotonic()

    logger.info(f"[{request_id}] Starting info extraction for: {_sanitize_for_log(request.url)}")

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
        metrics.record_error(operation="info_extraction", error=_truncate_error(str(e)), elapsed=elapsed)
        logger.warning(f"[{request_id}] Extraction error after {elapsed:.2f}s: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except NetworkError as e:
        elapsed = time.monotonic() - start_time
        metrics.record_error(operation="info_extraction", error=_truncate_error(str(e)), elapsed=elapsed)
        logger.warning(f"[{request_id}] Network error after {elapsed:.2f}s: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except CatLoaderError as e:
        elapsed = time.monotonic() - start_time
        metrics.record_error(operation="info_extraction", error=_truncate_error(str(e)), elapsed=elapsed)
        logger.warning(f"[{request_id}] Application error after {elapsed:.2f}s: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        elapsed = time.monotonic() - start_time
        metrics.record_error(operation="info_extraction", error=_truncate_error(str(e)), elapsed=elapsed)
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

    logger.info(f"[{request_id}] Starting download for: {_sanitize_for_log(validated_url)} (format={validated_format_id}, audio_only={audio_only})")

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
        metrics.record_error(operation="download", error=_truncate_error(str(e)), elapsed=elapsed)
        logger.warning(f"[{request_id}] File size limit exceeded after {elapsed:.2f}s: {e}")
        raise HTTPException(status_code=413, detail=str(e))
    except DownloadError as e:
        elapsed = time.monotonic() - start_time
        metrics.record_error(operation="download", error=_truncate_error(str(e)), elapsed=elapsed)
        logger.warning(f"[{request_id}] Download error after {elapsed:.2f}s: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except NetworkError as e:
        elapsed = time.monotonic() - start_time
        metrics.record_error(operation="download", error=_truncate_error(str(e)), elapsed=elapsed)
        logger.warning(f"[{request_id}] Network error after {elapsed:.2f}s: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except CatLoaderError as e:
        elapsed = time.monotonic() - start_time
        metrics.record_error(operation="download", error=_truncate_error(str(e)), elapsed=elapsed)
        logger.warning(f"[{request_id}] Application error after {elapsed:.2f}s: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        elapsed = time.monotonic() - start_time
        metrics.record_error(operation="download", error=_truncate_error(str(e)), elapsed=elapsed)
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
    """Stream download progress via Server-Sent Events.

    NOTE: This endpoint uses the same concurrency semaphore as other endpoints
    to prevent DoS attacks via many simultaneous SSE connections.
    """
    # Validate inputs
    validated_url = validate_url_for_http(url)
    validated_format_id = validate_format_id_for_http(format_id)

    # Acquire semaphore before starting the stream to prevent DoS
    # This limits how many simultaneous SSE connections can be active
    semaphore = _get_semaphore()
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=0.1)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=503,
            detail=f"Server at capacity ({MAX_CONCURRENT_OPERATIONS} concurrent operations). "
                   "Please try again later."
        )

    def event_generator():
        start_time = time.monotonic()
        try:
            for event in download_video_with_progress(validated_url, validated_format_id, audio_only):
                # Check if connection has exceeded maximum allowed time
                elapsed = time.monotonic() - start_time
                if elapsed > SSE_STREAM_TIMEOUT:
                    logger.warning(f"SSE stream timeout after {elapsed:.0f}s for {_sanitize_for_log(validated_url)}")
                    yield f"data: {json.dumps({'status': 'error', 'error_type': 'timeout', 'message': 'Connection timeout', 'retryable': True})}\n\n"
                    return
                yield event
        except NetworkError as e:
            # Transient network errors - client can retry
            elapsed = time.monotonic() - start_time
            logger.warning(f"Network error in download progress stream: {e}")
            metrics.record_error(operation="download_progress", error=_truncate_error(str(e)), elapsed=elapsed)
            yield f"data: {json.dumps({'status': 'error', 'error_type': 'network', 'message': str(e), 'retryable': True})}\n\n"
        except (DownloadError, CatLoaderError) as e:
            # Permanent errors - no point retrying
            elapsed = time.monotonic() - start_time
            logger.warning(f"Download error in progress stream: {e}")
            metrics.record_error(operation="download_progress", error=_truncate_error(str(e)), elapsed=elapsed)
            yield f"data: {json.dumps({'status': 'error', 'error_type': 'download', 'message': str(e), 'retryable': False})}\n\n"
        except Exception as e:
            # Unknown errors - log full traceback, assume not retryable
            elapsed = time.monotonic() - start_time
            logger.exception(f"Unexpected error in download progress stream: {e}")
            metrics.record_error(operation="download_progress", error=_truncate_error(str(e)), elapsed=elapsed)
            yield f"data: {json.dumps({'status': 'error', 'error_type': 'internal', 'message': str(e), 'retryable': False})}\n\n"
        # Note: Semaphore release is handled by SemaphoreGuardedIterator.close()
        # This guarantees release even if client disconnects before iteration starts

    # Wrap generator to guarantee semaphore release on close()
    # This solves the race condition where client disconnect before iteration
    # would leak the semaphore (generator's finally never executes)
    guarded_iterator = SemaphoreGuardedIterator(event_generator(), semaphore)

    return StreamingResponse(
        guarded_iterator,
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
    request_id = _generate_request_id()
    start_time = time.monotonic()

    # Validate download_id format to prevent processing malformed IDs
    validated_id = validate_download_id_for_http(download_id)

    logger.info(f"[{request_id}] Starting file download for ID: {validated_id[:8]}...")

    file_info = remove_completed_download(validated_id)

    if not file_info:
        elapsed = time.monotonic() - start_time
        logger.warning(f"[{request_id}] Download not found after {elapsed:.2f}s: {validated_id[:8]}...")
        raise HTTPException(status_code=404, detail="Download not found or expired")

    file_path = file_info.get('file_path')
    temp_dir = file_info.get('temp_dir')

    if not file_path or not temp_dir:
        elapsed = time.monotonic() - start_time
        logger.warning(f"[{request_id}] Invalid download state after {elapsed:.2f}s")
        if temp_dir:
            cleanup_temp_dir(temp_dir)
        raise HTTPException(status_code=404, detail="Invalid download state")

    # Validate file is within temp directory (prevent path traversal)
    try:
        real_file_path = os.path.realpath(file_path)
        real_temp_dir = os.path.realpath(temp_dir)
        if not real_file_path.startswith(real_temp_dir + os.sep):
            elapsed = time.monotonic() - start_time
            logger.error(f"[{request_id}] Path traversal attempt after {elapsed:.2f}s: {file_path}")
            cleanup_temp_dir(temp_dir)
            raise HTTPException(status_code=400, detail="Invalid file path")
    except OSError:
        elapsed = time.monotonic() - start_time
        logger.warning(f"[{request_id}] File not found after {elapsed:.2f}s")
        cleanup_temp_dir(temp_dir)
        raise HTTPException(status_code=404, detail="File not found")

    # Sanitize filename for header
    ascii_filename, encoded_filename = sanitize_filename(file_info.get('filename', 'download'))
    if not ascii_filename:
        ascii_filename = 'download'
        encoded_filename = 'download'

    elapsed = time.monotonic() - start_time
    file_size = file_info.get('file_size', 0)
    logger.info(f"[{request_id}] Streaming file in {elapsed:.2f}s: {ascii_filename} ({file_size} bytes)")

    def file_generator():
        try:
            with open(file_path, 'rb') as f:
                while chunk := f.read(CHUNK_SIZE):
                    yield chunk
        except FileNotFoundError:
            # Handle TOCTOU race - file was deleted between check and open
            logger.warning(f"[{request_id}] File disappeared during streaming: {file_path}")
        except Exception as e:
            logger.error(f"[{request_id}] Error streaming file: {e}")
        finally:
            cleanup_temp_dir(temp_dir)

    return StreamingResponse(
        file_generator(),
        media_type=file_info.get('content_type', 'application/octet-stream'),
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{encoded_filename}',
            "Content-Length": str(file_size),
            "Cache-Control": "no-cache",
        }
    )

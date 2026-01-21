import atexit
import json
import logging
import os
import queue
import secrets
import shutil
import tempfile
import threading
import time
from typing import Generator, Tuple, Dict, Any, Optional, NamedTuple, TypedDict

import yt_dlp

from ..models.schemas import VideoInfo, VideoFormat
from ..exceptions import VideoExtractionError, DownloadError, NetworkError, FileSizeLimitError
from ..config import (
    MAX_FILE_SIZE,
    YTDLP_SOCKET_TIMEOUT,
    DOWNLOAD_EXPIRY_SECONDS,
    MAX_COMPLETED_DOWNLOADS,
    CHUNK_SIZE,
    ORPHAN_CLEANUP_AGE_SECONDS,
    TEMP_DIR_PREFIX,
    YTDLP_USER_AGENT,
    PROGRESS_POLL_INTERVAL,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Type Definitions for yt-dlp hooks
# =============================================================================

class ProgressHookData(TypedDict, total=False):
    """Type hints for yt-dlp progress_hook callback data."""
    status: str  # 'downloading', 'finished', 'error'
    downloaded_bytes: int
    total_bytes: Optional[int]
    total_bytes_estimate: Optional[int]
    filename: str
    tmpfilename: str
    elapsed: float
    speed: Optional[float]
    eta: Optional[int]
    fragment_index: Optional[int]
    fragment_count: Optional[int]


class PostprocessorHookData(TypedDict, total=False):
    """Type hints for yt-dlp postprocessor_hook callback data."""
    status: str  # 'started', 'processing', 'finished'
    postprocessor: str
    info_dict: Dict[str, Any]


class DownloadResult(NamedTuple):
    """Result of a video/audio download operation."""
    filename: str
    content_type: str
    file_size: int
    stream: Generator[bytes, None, None]

# =============================================================================
# Local Constants (not configurable via environment)
# =============================================================================
# Note: Configurable constants are in config.py:
# - DOWNLOAD_EXPIRY_SECONDS, MAX_COMPLETED_DOWNLOADS, CHUNK_SIZE
# - ORPHAN_CLEANUP_AGE_SECONDS, TEMP_DIR_PREFIX, YTDLP_USER_AGENT
# - PROGRESS_POLL_INTERVAL

THREAD_JOIN_TIMEOUT = 2.0  # seconds to wait for thread on cancellation
DOWNLOAD_ID_BYTES = 32  # 256 bits of entropy for secure tokens

CONTENT_TYPES = {
    '.mp4': 'video/mp4',
    '.webm': 'video/webm',
    '.mkv': 'video/x-matroska',
    '.mp3': 'audio/mpeg',
    '.m4a': 'audio/mp4',
    '.opus': 'audio/opus',
    '.ogg': 'audio/ogg',
}


def get_content_type(ext: str) -> str:
    """Get content type for file extension."""
    return CONTENT_TYPES.get(ext.lower(), 'application/octet-stream')


# =============================================================================
# In-memory store for completed downloads
# =============================================================================
# In production, use Redis or similar
_completed_downloads: Dict[str, Dict[str, Any]] = {}
_downloads_lock = threading.Lock()
_cleanup_thread: Optional[threading.Thread] = None
_shutdown_event = threading.Event()


def _background_cleanup() -> None:
    """Periodically clean up expired downloads and orphaned temp directories."""
    while not _shutdown_event.wait(timeout=60):
        _cleanup_expired_downloads()
        _cleanup_orphaned_temp_dirs()


def _cleanup_expired_downloads() -> None:
    """Clean up expired downloads from the store."""
    # Collect dirs to clean while holding lock, then clean without lock
    dirs_to_clean = []
    with _downloads_lock:
        current_time = time.time()
        expired = [k for k, v in _completed_downloads.items()
                   if current_time - v.get('created_at', 0) > DOWNLOAD_EXPIRY_SECONDS]
        for k in expired:
            info = _completed_downloads.pop(k, None)
            if info and 'temp_dir' in info:
                dirs_to_clean.append(info['temp_dir'])

    # Do I/O cleanup outside of lock to avoid blocking other threads
    for temp_dir in dirs_to_clean:
        cleanup_temp_dir(temp_dir)

    if dirs_to_clean:
        logger.info(f"Cleaned up {len(dirs_to_clean)} expired downloads")


def _cleanup_orphaned_temp_dirs() -> None:
    """
    Clean up orphaned temp directories from failed/timed-out downloads.

    When a timeout occurs before download_video() returns, the temp directory
    is created but never tracked, leaving it orphaned. This function scans
    the system temp directory for old catloader_* directories and removes them.
    """
    temp_base = tempfile.gettempdir()
    current_time = time.time()
    cleaned_count = 0

    try:
        for entry in os.scandir(temp_base):
            # Only process directories with our prefix
            if not entry.is_dir() or not entry.name.startswith(TEMP_DIR_PREFIX):
                continue

            try:
                # Check directory age using modification time
                dir_mtime = entry.stat().st_mtime
                age_seconds = current_time - dir_mtime

                if age_seconds > ORPHAN_CLEANUP_AGE_SECONDS:
                    cleanup_temp_dir(entry.path)
                    cleaned_count += 1
            except OSError as e:
                # Directory might have been deleted by another process
                logger.debug(f"Could not check/clean orphan dir {entry.path}: {e}")
                continue

    except OSError as e:
        logger.warning(f"Error scanning temp directory for orphans: {e}")

    if cleaned_count > 0:
        logger.info(f"Cleaned up {cleaned_count} orphaned temp directories")


def _start_cleanup_thread() -> None:
    """Start the background cleanup thread."""
    global _cleanup_thread
    if _cleanup_thread is None or not _cleanup_thread.is_alive():
        _cleanup_thread = threading.Thread(target=_background_cleanup, daemon=True)
        _cleanup_thread.start()
        logger.debug("Started background cleanup thread")


def _shutdown_cleanup_thread() -> None:
    """Shutdown the background cleanup thread."""
    _shutdown_event.set()
    if _cleanup_thread and _cleanup_thread.is_alive():
        _cleanup_thread.join(timeout=5)
    logger.debug("Shutdown background cleanup thread")


# Start cleanup thread on module load
_start_cleanup_thread()
atexit.register(_shutdown_cleanup_thread)


def store_completed_download(file_info: Dict[str, Any]) -> str:
    """Store completed download info and return download ID."""
    # Use cryptographically secure token
    download_id = secrets.token_urlsafe(DOWNLOAD_ID_BYTES)

    # Create a copy to prevent external mutation
    stored_info = file_info.copy()
    stored_info['created_at'] = time.time()

    # Collect dirs to clean while holding lock
    dirs_to_clean = []

    with _downloads_lock:
        # Clean expired downloads (collect dirs only, don't do I/O)
        dirs_to_clean.extend(_collect_expired_downloads_locked())

        # Check capacity and remove oldest if needed
        if len(_completed_downloads) >= MAX_COMPLETED_DOWNLOADS:
            oldest_key = min(
                _completed_downloads.keys(),
                key=lambda k: _completed_downloads[k].get('created_at', 0)
            )
            old_info = _completed_downloads.pop(oldest_key)
            if old_info and 'temp_dir' in old_info:
                dirs_to_clean.append(old_info['temp_dir'])
            logger.warning("Evicted oldest download due to capacity limit")

        _completed_downloads[download_id] = stored_info

    # Do I/O cleanup outside of lock
    for temp_dir in dirs_to_clean:
        cleanup_temp_dir(temp_dir)

    return download_id


def _collect_expired_downloads_locked() -> list:
    """Collect and remove expired downloads (must be called with lock held).

    Returns list of temp_dir paths to clean up AFTER releasing lock.
    """
    dirs_to_clean = []
    current_time = time.time()
    expired = [k for k, v in _completed_downloads.items()
               if current_time - v.get('created_at', 0) > DOWNLOAD_EXPIRY_SECONDS]
    for k in expired:
        info = _completed_downloads.pop(k, None)
        if info and 'temp_dir' in info:
            dirs_to_clean.append(info['temp_dir'])
    return dirs_to_clean


def remove_completed_download(download_id: str) -> Optional[Dict[str, Any]]:
    """Remove and return completed download info."""
    with _downloads_lock:
        return _completed_downloads.pop(download_id, None)


# Common options to avoid 403 errors
COMMON_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'http_headers': {
        'User-Agent': YTDLP_USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-us,en;q=0.5',
    },
    'socket_timeout': YTDLP_SOCKET_TIMEOUT,
    'retries': 3,
}


def _configure_format_options(ydl_opts: Dict[str, Any], format_id: str, audio_only: bool) -> None:
    """
    Configure yt-dlp format options for download.

    This helper function eliminates duplication between download_video()
    and download_video_with_progress().

    Args:
        ydl_opts: yt-dlp options dictionary to modify in-place
        format_id: Format ID string or 'best'
        audio_only: Whether to download audio only
    """
    if audio_only:
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else:
        if format_id and format_id != 'best':
            ydl_opts['format'] = format_id
        else:
            ydl_opts['format'] = 'bestvideo+bestaudio/best'
        ydl_opts['merge_output_format'] = 'mp4'


def get_video_info(url: str) -> VideoInfo:
    """Extract video information without downloading."""
    ydl_opts = {
        **COMMON_OPTS,
        'extract_flat': False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e).lower()
        if 'unsupported url' in error_msg or 'is not a valid url' in error_msg:
            raise VideoExtractionError(f"Unsupported or invalid URL: {url}") from e
        elif 'network' in error_msg or 'connection' in error_msg or 'timeout' in error_msg:
            raise NetworkError(f"Network error while fetching video info: {e}") from e
        else:
            raise VideoExtractionError(f"Could not extract video information: {e}") from e
    except (OSError, ConnectionError, TimeoutError) as e:
        # Known transient errors - wrap as NetworkError for retry
        logger.warning(f"Transient error extracting video info for {url}: {e}")
        raise NetworkError(f"Network error: {e}") from e
    except Exception as e:
        # Unknown errors - log and re-raise without wrapping as transient
        # This prevents unnecessary retries for programming bugs
        logger.exception(f"Unexpected error extracting video info for {url}")
        raise VideoExtractionError(f"Unexpected error: {e}") from e

    if info is None:
        raise VideoExtractionError("Could not extract video information")

    video_formats = []
    audio_formats = []
    seen_resolutions = set()
    seen_audio = set()

    formats = info.get('formats', [])

    # Collect all available resolutions (including video-only formats)
    available_heights = set()
    best_audio_size = 0

    for fmt in formats:
        has_video = fmt.get('vcodec', 'none') != 'none'
        has_audio = fmt.get('acodec', 'none') != 'none'
        height = fmt.get('height')
        filesize = fmt.get('filesize') or fmt.get('filesize_approx') or 0

        if has_video and height:
            available_heights.add(height)

        # Track audio formats
        if has_audio and not has_video:
            abr = fmt.get('abr', 0)
            ext = fmt.get('ext', 'unknown')
            format_id = fmt.get('format_id', '')
            audio_key = f"{int(abr) if abr else 0}_{ext}"

            if abr and audio_key not in seen_audio:
                seen_audio.add(audio_key)
                audio_formats.append(VideoFormat(
                    format_id=format_id,
                    ext=ext,
                    resolution=None,
                    filesize=filesize if filesize else None,
                    has_audio=True,
                    has_video=False,
                    quality_label=f"{int(abr)}kbps ({ext.upper()})"
                ))
            if filesize > best_audio_size:
                best_audio_size = filesize

    # Create video format options for each resolution
    # Use yt-dlp format selection to combine best video at height + best audio
    for height in sorted(available_heights, reverse=True):
        resolution = f"{height}p"
        if resolution not in seen_resolutions:
            seen_resolutions.add(resolution)

            # Estimate total size (video + audio)
            video_size = 0
            for fmt in formats:
                if fmt.get('height') == height and fmt.get('vcodec', 'none') != 'none':
                    size = fmt.get('filesize') or fmt.get('filesize_approx') or 0
                    if size > video_size:
                        video_size = size

            total_size = video_size + best_audio_size if video_size else None

            # Format string that tells yt-dlp to get best video at this height + best audio
            format_string = f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"

            video_formats.append(VideoFormat(
                format_id=format_string,
                ext='mp4',
                resolution=resolution,
                filesize=total_size,
                has_audio=True,
                has_video=True,
                quality_label=f"{resolution} (MP4)"
            ))

    # Sort by quality (resolution/bitrate)
    video_formats.sort(
        key=lambda x: int(x.resolution.replace('p', '')) if x.resolution and x.resolution != 'best' else 0,
        reverse=True
    )
    audio_formats.sort(
        key=lambda x: int(x.quality_label.split('kbps')[0]) if x.quality_label and 'kbps' in x.quality_label else 0,
        reverse=True
    )

    # If no formats found, create fallback options
    if not video_formats:
        video_formats = [VideoFormat(
            format_id='bestvideo+bestaudio/best',
            ext='mp4',
            resolution='best',
            has_audio=True,
            has_video=True,
            quality_label='Best Quality (MP4)'
        )]

    if not audio_formats:
        audio_formats = [VideoFormat(
            format_id='bestaudio/best',
            ext='m4a',
            resolution=None,
            has_audio=True,
            has_video=False,
            quality_label='Best Audio (M4A)'
        )]

    return VideoInfo(
        title=info.get('title', 'Unknown'),
        thumbnail=info.get('thumbnail'),
        duration=info.get('duration'),
        uploader=info.get('uploader'),
        video_formats=video_formats[:10],
        audio_formats=audio_formats[:6],
    )


def cleanup_temp_dir(temp_dir: str) -> None:
    """Safely cleanup temporary directory and its contents."""
    try:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            logger.debug(f"Cleaned up temp directory: {temp_dir}")
    except OSError as e:
        logger.warning(f"Failed to cleanup temp directory {temp_dir}: {e}")


def download_video(url: str, format_id: str, audio_only: bool = False) -> DownloadResult:
    """
    Download video/audio and return a DownloadResult with file info and stream.

    Returns:
        DownloadResult with filename, content_type, file_size, and stream generator

    Raises:
        DownloadError: If download fails
        NetworkError: If network error occurs
    """
    temp_dir = tempfile.mkdtemp(prefix=TEMP_DIR_PREFIX)
    output_template = os.path.join(temp_dir, '%(title)s.%(ext)s')

    ydl_opts = {
        **COMMON_OPTS,
        'outtmpl': output_template,
    }
    _configure_format_options(ydl_opts, format_id, audio_only)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        cleanup_temp_dir(temp_dir)
        error_msg = str(e).lower()
        if 'network' in error_msg or 'connection' in error_msg or 'timeout' in error_msg:
            raise NetworkError(f"Network error during download: {e}") from e
        raise DownloadError(f"Download failed: {e}") from e
    except (OSError, ConnectionError, TimeoutError) as e:
        # Known transient errors - wrap as NetworkError for retry
        cleanup_temp_dir(temp_dir)
        logger.warning(f"Transient error downloading {url}: {e}")
        raise NetworkError(f"Network error during download: {e}") from e
    except Exception as e:
        # Unknown errors - log and re-raise without wrapping as transient
        # This prevents unnecessary retries for programming bugs
        cleanup_temp_dir(temp_dir)
        logger.exception(f"Unexpected error downloading {url}")
        raise DownloadError(f"Unexpected error during download: {e}") from e

    if info is None:
        cleanup_temp_dir(temp_dir)
        raise DownloadError("Could not download video")

    # Get the downloaded file path from yt-dlp's info dict
    # This is more reliable than scanning the directory because yt-dlp creates
    # intermediate files during merging (e.g., .part, .temp, separate audio/video)
    downloaded_file = None

    # Primary method: use requested_downloads which contains the final file path
    if 'requested_downloads' in info and info['requested_downloads']:
        downloaded_file = info['requested_downloads'][0].get('filepath')

    # Fallback: use _filename if available (older yt-dlp versions)
    if not downloaded_file and '_filename' in info:
        downloaded_file = info['_filename']

    # Last resort: scan directory for files matching expected extensions
    # This handles edge cases where yt-dlp doesn't populate the info dict correctly
    if not downloaded_file or not os.path.isfile(downloaded_file):
        expected_extensions = {'.mp4', '.webm', '.mkv', '.mp3', '.m4a', '.opus', '.ogg', '.wav'}
        # Skip intermediate files that yt-dlp creates during processing
        skip_extensions = {'.part', '.temp', '.ytdl', '.frag'}

        # First pass: look for files with expected extensions (preferred)
        for file in os.listdir(temp_dir):
            file_path = os.path.join(temp_dir, file)
            if os.path.isfile(file_path):
                ext = os.path.splitext(file)[1].lower()
                if ext in expected_extensions:
                    downloaded_file = file_path
                    break

        # Second pass: if no expected extension found, accept any non-intermediate file
        if not downloaded_file:
            for file in os.listdir(temp_dir):
                file_path = os.path.join(temp_dir, file)
                if os.path.isfile(file_path):
                    ext = os.path.splitext(file)[1].lower()
                    if ext not in skip_extensions:
                        downloaded_file = file_path
                        break

    if not downloaded_file or not os.path.isfile(downloaded_file):
        cleanup_temp_dir(temp_dir)
        raise DownloadError("Download completed but file not found")

    filename = os.path.basename(downloaded_file)
    file_size = os.path.getsize(downloaded_file)

    # Check file size limit (0 means no limit)
    if MAX_FILE_SIZE > 0 and file_size > MAX_FILE_SIZE:
        cleanup_temp_dir(temp_dir)
        size_mb = file_size / (1024 * 1024)
        limit_mb = MAX_FILE_SIZE / (1024 * 1024)
        raise FileSizeLimitError(
            f"File size ({size_mb:.1f} MB) exceeds maximum allowed ({limit_mb:.1f} MB)"
        )

    ext = os.path.splitext(filename)[1].lower()
    content_type = get_content_type(ext)

    def file_generator() -> Generator[bytes, None, None]:
        """Generator that streams file and cleans up when done or on error."""
        try:
            with open(downloaded_file, 'rb') as f:
                while chunk := f.read(CHUNK_SIZE):
                    yield chunk
        except GeneratorExit:
            # Client cancelled the download
            logger.info(f"Client cancelled download: {filename}")
        except Exception as e:
            logger.error(f"Error streaming file {filename}: {e}")
        finally:
            cleanup_temp_dir(temp_dir)

    return DownloadResult(
        filename=filename,
        content_type=content_type,
        file_size=file_size,
        stream=file_generator()
    )


def download_video_with_progress(url: str, format_id: str, audio_only: bool = False) -> Generator[str, None, None]:
    """
    Download video/audio and yield SSE events with progress updates.

    Yields:
        SSE-formatted strings with progress data
    """
    temp_dir = tempfile.mkdtemp(prefix=TEMP_DIR_PREFIX)
    output_template = os.path.join(temp_dir, '%(title)s.%(ext)s')
    progress_queue: queue.Queue = queue.Queue()
    download_complete = threading.Event()
    cancelled = threading.Event()
    download_error: Dict[str, Any] = {}

    def progress_hook(d: ProgressHookData) -> None:
        """Hook called by yt-dlp with download progress."""
        # Check if cancelled
        if cancelled.is_set():
            raise Exception("Download cancelled by client")

        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            speed = d.get('speed', 0)
            eta = d.get('eta', 0)

            if total > 0:
                percent = (downloaded / total) * 100
            else:
                percent = 0

            progress_queue.put({
                'status': 'downloading',
                'percent': round(percent, 1),
                'downloaded': downloaded,
                'total': total,
                'speed': speed,
                'eta': eta,
            })
        elif d['status'] == 'finished':
            progress_queue.put({
                'status': 'processing',
                'percent': 100,
                'message': 'Processing file...',
            })

    def postprocessor_hook(d: PostprocessorHookData) -> None:
        """Hook called by yt-dlp during post-processing."""
        if cancelled.is_set():
            raise Exception("Download cancelled by client")

        if d['status'] == 'started':
            progress_queue.put({
                'status': 'processing',
                'percent': 100,
                'message': 'Converting...',
            })

    def download_thread() -> None:
        """Run download in separate thread to not block SSE."""
        nonlocal download_error

        ydl_opts = {
            **COMMON_OPTS,
            'outtmpl': output_template,
            'progress_hooks': [progress_hook],
            'postprocessor_hooks': [postprocessor_hook],
        }
        _configure_format_options(ydl_opts, format_id, audio_only)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
        except Exception as e:
            if not cancelled.is_set():
                download_error['error'] = str(e)
        finally:
            download_complete.set()

    # Start download in background thread (daemon for clean shutdown)
    thread = threading.Thread(target=download_thread, daemon=True)
    thread.start()

    client_disconnected = False
    try:
        # Yield progress events
        while not download_complete.is_set() or not progress_queue.empty():
            try:
                progress = progress_queue.get(timeout=PROGRESS_POLL_INTERVAL)
                yield f"data: {json.dumps(progress)}\n\n"
            except queue.Empty:
                # Send heartbeat to keep connection alive
                if not download_complete.is_set():
                    yield f"data: {json.dumps({'status': 'waiting'})}\n\n"
    except GeneratorExit:
        # Client disconnected - signal cancellation and cleanup
        client_disconnected = True
        cancelled.set()
        logger.info(f"Client disconnected, cancelling download for {url}")
    finally:
        if client_disconnected:
            # Wait briefly for thread to notice cancellation
            thread.join(timeout=THREAD_JOIN_TIMEOUT)
            cleanup_temp_dir(temp_dir)
            return

    thread.join()

    # Check for errors
    if download_error:
        cleanup_temp_dir(temp_dir)
        yield f"data: {json.dumps({'status': 'error', 'message': download_error['error']})}\n\n"
        return

    # Find downloaded file
    downloaded_file = None
    for file in os.listdir(temp_dir):
        file_path = os.path.join(temp_dir, file)
        if os.path.isfile(file_path):
            downloaded_file = file_path
            break

    if not downloaded_file:
        cleanup_temp_dir(temp_dir)
        yield f"data: {json.dumps({'status': 'error', 'message': 'File not found'})}\n\n"
        return

    filename = os.path.basename(downloaded_file)
    file_size = os.path.getsize(downloaded_file)
    ext = os.path.splitext(filename)[1].lower()
    content_type = get_content_type(ext)

    # Store file info for the download endpoint to retrieve
    safe_filename = filename.encode('ascii', 'ignore').decode('ascii')
    if not safe_filename:
        safe_filename = "download" + (".mp3" if audio_only else ".mp4")

    # Store download info and get ID
    download_id = store_completed_download({
        'filename': safe_filename,
        'file_size': file_size,
        'content_type': content_type,
        'temp_dir': temp_dir,
        'file_path': downloaded_file,
    })

    yield f"data: {json.dumps({'status': 'complete', 'download_id': download_id, 'filename': safe_filename, 'file_size': file_size})}\n\n"

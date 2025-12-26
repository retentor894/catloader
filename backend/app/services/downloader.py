import yt_dlp
import tempfile
import os
import shutil
import logging
import json
import queue
import threading
import uuid
import time
from typing import Generator, Tuple, Dict, Any, Optional
from ..models.schemas import VideoInfo, VideoFormat
from ..exceptions import VideoExtractionError, DownloadError, NetworkError


# In-memory store for completed downloads (download_id -> file_info)
# In production, use Redis or similar
_completed_downloads: Dict[str, Dict[str, Any]] = {}
_downloads_lock = threading.Lock()
DOWNLOAD_EXPIRY_SECONDS = 300  # 5 minutes


def store_completed_download(file_info: Dict[str, Any]) -> str:
    """Store completed download info and return download ID."""
    download_id = str(uuid.uuid4())
    file_info['created_at'] = time.time()

    with _downloads_lock:
        # Clean expired downloads
        current_time = time.time()
        expired = [k for k, v in _completed_downloads.items()
                   if current_time - v.get('created_at', 0) > DOWNLOAD_EXPIRY_SECONDS]
        for k in expired:
            info = _completed_downloads.pop(k, None)
            if info and 'temp_dir' in info:
                cleanup_temp_dir(info['temp_dir'])

        _completed_downloads[download_id] = file_info

    return download_id


def get_completed_download(download_id: str) -> Optional[Dict[str, Any]]:
    """Get completed download info by ID."""
    with _downloads_lock:
        return _completed_downloads.get(download_id)


def remove_completed_download(download_id: str) -> Optional[Dict[str, Any]]:
    """Remove and return completed download info."""
    with _downloads_lock:
        return _completed_downloads.pop(download_id, None)

logger = logging.getLogger(__name__)


# Common options to avoid 403 errors
COMMON_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-us,en;q=0.5',
    },
    'socket_timeout': 30,
    'retries': 3,
}


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
    except Exception as e:
        logger.exception(f"Unexpected error extracting video info for {url}")
        raise NetworkError(f"Unexpected error: {e}") from e

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


def download_video(url: str, format_id: str, audio_only: bool = False) -> Tuple[str, str, int, Generator[bytes, None, None]]:
    """
    Download video/audio and return filename, content_type, file_size, and file stream.

    Returns:
        Tuple of (filename, content_type, file_size, generator)

    Raises:
        DownloadError: If download fails
        NetworkError: If network error occurs
    """
    temp_dir = tempfile.mkdtemp()
    output_template = os.path.join(temp_dir, '%(title)s.%(ext)s')

    ydl_opts = {
        **COMMON_OPTS,
        'outtmpl': output_template,
    }

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

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        cleanup_temp_dir(temp_dir)
        error_msg = str(e).lower()
        if 'network' in error_msg or 'connection' in error_msg or 'timeout' in error_msg:
            raise NetworkError(f"Network error during download: {e}") from e
        raise DownloadError(f"Download failed: {e}") from e
    except Exception as e:
        cleanup_temp_dir(temp_dir)
        logger.exception(f"Unexpected error downloading {url}")
        raise NetworkError(f"Unexpected error during download: {e}") from e

    if info is None:
        cleanup_temp_dir(temp_dir)
        raise DownloadError("Could not download video")

    # Find the downloaded file
    downloaded_file = None
    for file in os.listdir(temp_dir):
        file_path = os.path.join(temp_dir, file)
        if os.path.isfile(file_path):
            downloaded_file = file_path
            break

    if not downloaded_file:
        cleanup_temp_dir(temp_dir)
        raise DownloadError("Download completed but file not found")

    filename = os.path.basename(downloaded_file)
    file_size = os.path.getsize(downloaded_file)
    ext = os.path.splitext(filename)[1].lower()

    content_types = {
        '.mp4': 'video/mp4',
        '.webm': 'video/webm',
        '.mkv': 'video/x-matroska',
        '.mp3': 'audio/mpeg',
        '.m4a': 'audio/mp4',
        '.opus': 'audio/opus',
        '.ogg': 'audio/ogg',
    }
    content_type = content_types.get(ext, 'application/octet-stream')

    def file_generator() -> Generator[bytes, None, None]:
        """Generator that streams file and cleans up when done or on error."""
        try:
            with open(downloaded_file, 'rb') as f:
                while chunk := f.read(8192):
                    yield chunk
        except GeneratorExit:
            # Client cancelled the download
            logger.info(f"Client cancelled download: {filename}")
        except Exception as e:
            logger.error(f"Error streaming file {filename}: {e}")
        finally:
            cleanup_temp_dir(temp_dir)

    return filename, content_type, file_size, file_generator()


def download_video_with_progress(url: str, format_id: str, audio_only: bool = False) -> Generator[str, None, None]:
    """
    Download video/audio and yield SSE events with progress updates.

    Yields:
        SSE-formatted strings with progress data
    """
    temp_dir = tempfile.mkdtemp()
    output_template = os.path.join(temp_dir, '%(title)s.%(ext)s')
    progress_queue: queue.Queue = queue.Queue()
    download_complete = threading.Event()
    cancelled = threading.Event()
    download_error: Dict[str, Any] = {}

    def progress_hook(d: Dict[str, Any]) -> None:
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

    def postprocessor_hook(d: Dict[str, Any]) -> None:
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

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
        except Exception as e:
            if not cancelled.is_set():
                download_error['error'] = str(e)
        finally:
            download_complete.set()

    # Start download in background thread
    thread = threading.Thread(target=download_thread)
    thread.start()

    client_disconnected = False
    try:
        # Yield progress events
        while not download_complete.is_set() or not progress_queue.empty():
            try:
                progress = progress_queue.get(timeout=0.5)
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
            thread.join(timeout=2.0)
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

    content_types = {
        '.mp4': 'video/mp4',
        '.webm': 'video/webm',
        '.mkv': 'video/x-matroska',
        '.mp3': 'audio/mpeg',
        '.m4a': 'audio/mp4',
        '.opus': 'audio/opus',
        '.ogg': 'audio/ogg',
    }
    content_type = content_types.get(ext, 'application/octet-stream')

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

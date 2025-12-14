import yt_dlp
import tempfile
import os
from typing import Optional, Generator, Tuple
from ..models.schemas import VideoInfo, VideoFormat


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

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

        if info is None:
            raise ValueError("Could not extract video information")

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
            video_formats=video_formats[:10],  # More options
            audio_formats=audio_formats[:6],   # More audio options
        )


def download_video(url: str, format_id: str, audio_only: bool = False) -> Tuple[str, str, Generator[bytes, None, None]]:
    """
    Download video/audio and return filename, content_type, and file stream.
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

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

        if info is None:
            raise ValueError("Could not download video")

        # Find the downloaded file
        downloaded_file = None
        for file in os.listdir(temp_dir):
            file_path = os.path.join(temp_dir, file)
            if os.path.isfile(file_path):
                downloaded_file = file_path
                break

        if not downloaded_file:
            raise ValueError("Download completed but file not found")

        filename = os.path.basename(downloaded_file)
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
            try:
                with open(downloaded_file, 'rb') as f:
                    while chunk := f.read(8192):
                        yield chunk
            finally:
                # Cleanup temp files
                try:
                    os.remove(downloaded_file)
                    os.rmdir(temp_dir)
                except:
                    pass

        return filename, content_type, file_generator()

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from urllib.parse import unquote
from ..models.schemas import URLRequest, VideoInfo, ErrorResponse
from ..services.downloader import (
    get_video_info,
    download_video,
    download_video_with_progress,
    get_completed_download,
    remove_completed_download,
    cleanup_temp_dir,
)
from ..exceptions import VideoExtractionError, DownloadError, NetworkError, CatLoaderError

router = APIRouter(prefix="/api", tags=["download"])

# Thread pool for blocking operations
_executor = ThreadPoolExecutor(max_workers=4)


async def run_in_executor(func, *args, **kwargs):
    """Run a blocking function in thread pool."""
    loop = asyncio.get_event_loop()
    if kwargs:
        func = partial(func, **kwargs)
    return await loop.run_in_executor(_executor, func, *args)


@router.post("/info", response_model=VideoInfo, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def get_info(request: URLRequest):
    """Get video information and available formats."""
    try:
        info = await run_in_executor(get_video_info, request.url)
        return info
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
        decoded_url = unquote(url)
        filename, content_type, file_size, file_stream = await run_in_executor(
            download_video, decoded_url, format_id, audio_only
        )

        # Sanitize filename for Content-Disposition header
        safe_filename = filename.encode('ascii', 'ignore').decode('ascii')
        if not safe_filename:
            safe_filename = "download" + (".mp3" if audio_only else ".mp4")

        return StreamingResponse(
            file_stream,
            media_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{safe_filename}"',
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
    decoded_url = unquote(url)

    def event_generator():
        yield from download_video_with_progress(decoded_url, format_id, audio_only)

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
    if not file_path or not os.path.exists(file_path):
        if 'temp_dir' in file_info:
            cleanup_temp_dir(file_info['temp_dir'])
        raise HTTPException(status_code=404, detail="File not found")

    def file_generator():
        try:
            with open(file_path, 'rb') as f:
                while chunk := f.read(8192):
                    yield chunk
        finally:
            cleanup_temp_dir(file_info['temp_dir'])

    return StreamingResponse(
        file_generator(),
        media_type=file_info['content_type'],
        headers={
            "Content-Disposition": f'attachment; filename="{file_info["filename"]}"',
            "Content-Length": str(file_info['file_size']),
            "Cache-Control": "no-cache",
        }
    )

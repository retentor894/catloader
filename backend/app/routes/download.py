import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from urllib.parse import unquote
from ..models.schemas import URLRequest, VideoInfo, ErrorResponse
from ..services.downloader import get_video_info, download_video
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
        filename, content_type, file_stream = await run_in_executor(
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

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from urllib.parse import unquote
from ..models.schemas import URLRequest, VideoInfo, ErrorResponse
from ..services.downloader import get_video_info, download_video

router = APIRouter(prefix="/api", tags=["download"])


@router.post("/info", response_model=VideoInfo, responses={400: {"model": ErrorResponse}})
async def get_info(request: URLRequest):
    """Get video information and available formats."""
    try:
        info = get_video_info(request.url)
        return info
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/download")
async def download(
    url: str = Query(..., description="Video URL"),
    format_id: str = Query("best", description="Format ID to download"),
    audio_only: bool = Query(False, description="Download audio only")
):
    """Download video or audio file."""
    try:
        decoded_url = unquote(url)
        filename, content_type, file_stream = download_video(
            decoded_url, format_id, audio_only
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
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

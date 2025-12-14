# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CatLoader is a video downloader web application that supports 1000+ sites via yt-dlp. It consists of a Python/FastAPI backend and a vanilla HTML/CSS/JS frontend.

## Commands

### Development (Local)

```bash
# Backend (Terminal 1)
cd backend
pip install -r requirements.txt
uvicorn app.main:app --port 8000 --reload

# Frontend (Terminal 2)
cd frontend
python -m http.server 5500
# Access at http://localhost:5500
```

### Production (Docker)

```bash
docker-compose up --build
# Access at http://localhost:8080
```

### Update yt-dlp (when downloads fail with 403)

```bash
pip install -U yt-dlp
```

## Architecture

```
catloader/
├── backend/                    # Python FastAPI
│   └── app/
│       ├── main.py            # FastAPI app, CORS config
│       ├── routes/download.py # API endpoints
│       ├── services/downloader.py # yt-dlp integration
│       └── models/schemas.py  # Pydantic models
├── frontend/                   # Vanilla HTML/CSS/JS
│   ├── index.html
│   ├── css/style.css
│   ├── js/app.js              # API calls, UI logic
│   └── nginx.conf             # Reverse proxy config for Docker
└── docker-compose.yml
```

## API Endpoints

- `POST /api/info` - Extract video metadata and available formats
- `GET /api/download?url=...&format_id=...&audio_only=...` - Stream video/audio download

## Key Implementation Details

- **Format selection**: Uses yt-dlp format strings like `bestvideo[height<=1080]+bestaudio` to combine separate video/audio streams
- **Streaming**: Downloads are streamed to client via `StreamingResponse`, temp files cleaned up after transfer
- **CORS**: Enabled for all origins in development; nginx proxies `/api/` in Docker
- **Frontend API URL**: Automatically detects Docker (port 8080) vs local dev to set correct backend URL

## Common Issues

- **403 errors on YouTube**: Update yt-dlp (`pip install -U yt-dlp`)
- **Only low quality formats**: Don't use `extractor_args` with `player_client` - it limits available formats
- **Python 3.8 compatibility**: Use `List[Type]` and `Tuple[...]` from typing instead of `list[Type]`

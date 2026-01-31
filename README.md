# CatLoader

Video downloader web application supporting 1000+ sites including YouTube, Vimeo, Twitter/X, TikTok, Facebook, Instagram, and more.

## Features

- Download videos in multiple qualities (4K, 1080p, 720p, 480p, etc.)
- Extract audio only (MP3)
- Clean, responsive UI (mobile-friendly)
- No registration required
- Docker support for easy deployment

## Requirements

### Local Development

- Python 3.9+ (3.11 recommended)
- FFmpeg (for audio extraction)
- Node.js 18+ (for E2E tests only)

### Docker

- Docker
- Docker Compose

## Installation

### Option 1: Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/yourusername/catloader.git
cd catloader

# Build and run
docker-compose up --build

# Access the app at http://localhost:8080
```

### Option 2: Local Development

#### 1. Install FFmpeg

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt update && sudo apt install ffmpeg

# Windows (using Chocolatey)
choco install ffmpeg
```

#### 2. Setup Backend

```bash
cd backend

# Create virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn app.main:app --port 8000 --reload
```

#### 3. Setup Frontend

```bash
cd frontend

# Serve the frontend (using Python's built-in server)
python -m http.server 5500

# Access the app at http://localhost:5500
```

## Usage

1. Open the app in your browser
2. Paste a video URL (e.g., `https://www.youtube.com/watch?v=...`)
3. Click "Get Video" or press Enter
4. Select your preferred quality from the available options
5. Click the format button to start the download

### Supported Sites

CatLoader uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) under the hood, which supports 1000+ sites including:

- YouTube
- Vimeo
- Twitter/X
- TikTok
- Facebook
- Instagram
- Twitch
- Reddit
- And many more...

For a full list of supported sites, see [yt-dlp supported sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md).

## API Reference

### Get Video Information

```http
POST /api/info
Content-Type: application/json

{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
}
```

**Response:**

```json
{
  "title": "Video Title",
  "thumbnail": "https://...",
  "duration": 212,
  "uploader": "Channel Name",
  "video_formats": [
    {
      "format_id": "bestvideo[height<=1080]+bestaudio",
      "ext": "mp4",
      "resolution": "1080p",
      "filesize": 52428800,
      "quality_label": "1080p (MP4)"
    }
  ],
  "audio_formats": [
    {
      "format_id": "140",
      "ext": "m4a",
      "quality_label": "128kbps (M4A)"
    }
  ]
}
```

### Download Video/Audio

```http
GET /api/download?url={video_url}&format_id={format}&audio_only={true|false}
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| url | string | Yes | Video URL (URL-encoded) |
| format_id | string | No | Format ID from /api/info (default: "best") |
| audio_only | boolean | No | Download audio only (default: false) |

**Response:** Binary file stream with appropriate Content-Type header.

### Health Check

```http
GET /health
```

**Response:**

```json
{
  "status": "healthy"
}
```

## Testing

### Backend Tests

```bash
cd backend

# Install test dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest

# Run with coverage report
pytest --cov=app --cov-report=html

# Run only unit tests
pytest app/tests/unit/ -v

# Run only integration tests
pytest app/tests/integration/ -v

# Run a specific test
pytest app/tests/unit/test_downloader.py::TestGetVideoInfo -v
```

### Frontend E2E Tests

```bash
cd frontend

# Install dependencies
npm install

# Install Playwright browsers
npx playwright install

# Run all E2E tests
npm run test:e2e

# Run in UI mode (interactive)
npm run test:e2e:ui

# Run in headed mode (see browser)
npm run test:e2e:headed

# View test report
npm run test:e2e:report
```

**Note:** E2E tests require the backend to be running on port 8000 and frontend on port 5500.

## Project Structure

```
catloader/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application
│   │   ├── routes/
│   │   │   └── download.py      # API endpoints
│   │   ├── services/
│   │   │   └── downloader.py    # yt-dlp integration
│   │   ├── models/
│   │   │   └── schemas.py       # Pydantic models
│   │   └── tests/
│   │       ├── conftest.py      # Test fixtures
│   │       ├── unit/            # Unit tests
│   │       └── integration/     # Integration tests
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/
│   ├── index.html
│   ├── css/
│   │   └── style.css
│   ├── js/
│   │   └── app.js
│   ├── tests/
│   │   ├── e2e/                 # Playwright E2E tests
│   │   └── fixtures/            # Mock data
│   ├── nginx.conf
│   ├── Dockerfile
│   ├── package.json
│   └── playwright.config.js
├── docker-compose.yml
├── CLAUDE.md
└── README.md
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| PORT | 8000 | Backend server port |
| PYTHONUNBUFFERED | 1 | Python output buffering |
| CORS_ORIGINS | http://localhost:5500,http://localhost:8080,http://127.0.0.1:5500 | Comma-separated list of allowed CORS origins. Use `*` to allow all origins (not recommended for production with credentials). |

### Docker Ports

| Service | Internal Port | External Port |
|---------|---------------|---------------|
| Backend | 8000 | - (internal only) |
| Frontend | 80 | 8080 |

## Troubleshooting

### "403 Forbidden" Error

YouTube and other sites frequently update their anti-bot measures. Update yt-dlp:

```bash
pip install -U yt-dlp
```

### "FFmpeg not found" Error

FFmpeg is required for merging video/audio streams and audio extraction. Install it:

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg
```

### Only Low Quality Options Available

This can happen with certain yt-dlp configurations. The app is configured to show all available qualities. If you see limited options, try:

1. Update yt-dlp: `pip install -U yt-dlp`
2. Restart the backend server

### CORS Errors in Browser

If running locally, make sure:

1. Backend is running on port 8000
2. Frontend is served via HTTP server (not opened as file://)
3. Use `http://localhost:5500` for the frontend

### Port Already in Use

```bash
# Find and kill process using port 8000
lsof -ti:8000 | xargs kill -9

# Or use a different port
uvicorn app.main:app --port 8001
```

## Development

### Code Style

```bash
# Format code with Black
black app/

# Lint with Flake8
flake8 app/
```

### Adding New Features

1. Create a feature branch
2. Write tests first (TDD recommended)
3. Implement the feature
4. Ensure all tests pass
5. Submit a pull request

## License

MIT License - see LICENSE file for details.

## Acknowledgments

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - Video download engine
- [FastAPI](https://fastapi.tiangolo.com/) - Backend framework
- [Playwright](https://playwright.dev/) - E2E testing framework




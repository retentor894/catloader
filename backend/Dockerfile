FROM python:3.11-slim

WORKDIR /app

# Install ffmpeg for audio extraction, curl for healthcheck, and unzip for deno
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Deno (JavaScript runtime required by yt-dlp for YouTube)
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

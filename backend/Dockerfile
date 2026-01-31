FROM python:3.11-slim

WORKDIR /app

# Install ffmpeg for audio extraction, curl for healthcheck, and unzip for deno
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Deno (JavaScript runtime required by yt-dlp for YouTube)
# Pinned version with checksum verification for supply chain security
ARG DENO_VERSION=2.1.4
ARG DENO_CHECKSUM=54a81939cccb2af114c4d0a68a554cf4a04b1f08728e70f663f83781de19d785
RUN curl -fsSL "https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-x86_64-unknown-linux-gnu.zip" -o /tmp/deno.zip \
    && echo "${DENO_CHECKSUM}  /tmp/deno.zip" | sha256sum -c - \
    && unzip -q /tmp/deno.zip -d /usr/local/bin \
    && chmod +x /usr/local/bin/deno \
    && rm /tmp/deno.zip

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Multi-platform slim Python 3.11 image for DigitalOcean Droplets
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install system dependencies (build tools for numpy/scipy if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency requirements
COPY requirements.txt .

# Install Python packages
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy application source code
COPY . .

# Ensure volume directories exist
RUN mkdir -p data/raw data/processed reports

# Health check
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('https://api.mexc.com/api/v3/ping', timeout=5)" || exit 1

# Default command: launch live momentum scanner daemon
CMD ["python", "run_scanner.py", "--interval", "5m", "--poll-sec", "60", "--top-coins", "40", "--min-score", "80", "--trade-size", "1.0"]

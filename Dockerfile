# Use a more robust base image than Alpine for Python apps with C-extensions
FROM python:3.12-slim-bookworm

# Set working directory
WORKDIR /app

# Install system dependencies
# We need libxml2 and libxslt for lxml (used by newspaper4k)
# We need sqlite3 for our database operations
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1 \
    libc6 \
    sqlite3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster and more reliable dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies using uv
# --frozen ensures we use the exact versions from uv.lock
# --no-dev excludes development dependencies
RUN uv sync --frozen --no-dev --no-install-project

# Copy project files
COPY mingpao_hkga_archiver.py .
COPY newspaper_extractor.py .
COPY config.docker.json ./config.json

# Create necessary directories
RUN mkdir -p /data /logs /app/output

# Set environment variables
ENV DB_PATH=/data/hkga_archive.db \
    LOG_PATH=/logs/hkga_archiver.log \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Use the virtual environment created by uv
ENTRYPOINT ["python", "mingpao_hkga_archiver.py"]
CMD ["--help"]

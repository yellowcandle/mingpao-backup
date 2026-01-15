FROM python:3.12-slim-bookworm

# Install system dependencies FIRST (rarely changes, maximizes cache hits)
# Using BuildKit cache mount for apt to speed up rebuilds
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    ca-certificates \
    libxml2 \
    libxslt1.1

# Set working directory
WORKDIR /app

# Install uv for dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies using uv into a virtual environment
# --frozen ensures we use the exact versions from uv.lock
# --no-dev excludes development dependencies
# Using BuildKit cache mount for uv cache
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

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

# Alpine-based minimal image
FROM python:3.12-alpine

WORKDIR /app

# Install runtime dependencies and build dependencies
# lxml and other packages may need gcc/musl-dev during pip install
RUN apk add --no-cache \
    libxml2 \
    libxslt \
    libstdc++ \
    sqlite \
    && apk add --no-cache --virtual .build-deps \
    gcc \
    musl-dev \
    libxml2-dev \
    libxslt-dev \
    python3-dev \
    && pip install --no-cache-dir --upgrade pip

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && apk del .build-deps \
    && rm -rf /root/.cache

# Copy project files
COPY mingpao_hkga_archiver.py .
COPY newspaper_extractor.py .
COPY config.docker.json ./config.json

# Create directories
RUN mkdir -p /data /logs /app/output

# Environment
ENV DB_PATH=/data/hkga_archive.db \
    LOG_PATH=/logs/archiver.log \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["python", "mingpao_hkga_archiver.py"]
CMD ["--help"]

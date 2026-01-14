# Alpine-based minimal image
FROM python:3.14-alpine

WORKDIR /app

# Install minimal runtime dependencies and Python packages
RUN apk add --no-cache --virtual .build-deps gcc musl-dev \
    && pip install --no-cache-dir \
        requests>=2.31.0 \
        internetarchive>=5.7.1 \
        pydantic>=2.0.0 \
    && apk del .build-deps \
    && rm -rf /root/.cache

# Copy only necessary files
COPY mingpao_hkga_archiver.py .
COPY config.docker.json ./config.json

# Create directories
RUN mkdir -p /data /logs

# Environment
ENV DB_PATH=/data/hkga_archive.db \
    LOG_PATH=/logs/archiver.log \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["python", "mingpao_hkga_archiver.py"]
CMD ["--help"]

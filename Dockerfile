ARG BASE_IMAGE=python:3.12-slim-bookworm
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PHOTOCRAFT_CONFIG_DIR=/data
WORKDIR /app
COPY requirements-lock.txt ./
ARG PIP_INDEX_URL=https://pypi.org/simple
# Install the build backend in the cached dependency layer as well.
RUN python -m pip install --no-cache-dir -r requirements-lock.txt "setuptools>=75" wheel
COPY pyproject.toml setup.py README.md LICENSE THIRD_PARTY_NOTICES.md ./
COPY photocraft ./photocraft
COPY scripts/write_build_info.py ./scripts/write_build_info.py
ARG VCS_REF=""
ARG VERSION_TAG=""
ARG VCS_COUNT="0"
ARG VCS_DIRTY="0"
RUN python scripts/write_build_info.py \
    && python -m pip install --no-cache-dir --no-deps --no-build-isolation . \
    && groupadd --gid 10001 photocraft \
    && useradd --uid 10001 --gid photocraft --no-create-home photocraft \
    && mkdir -p /data && chown photocraft:photocraft /data
LABEL org.opencontainers.image.title="PhotoCraft" \
      org.opencontainers.image.description="Self-hosted photo editor" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${VERSION_TAG}"
USER 10001:10001
EXPOSE 8000
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/api/health', timeout=3)" || exit 1
CMD ["python", "-m", "photocraft", "--host", "0.0.0.0", "--port", "8000"]

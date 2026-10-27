FROM python:3.11-slim

# Install OS Dependencies (curl: container healthcheck + debugging)
RUN apt-get update && apt-get install -y \
    curl \
    ffmpeg \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt requirements-embed.txt ./
# Local embedder is optional: WITH_LOCAL_EMBEDDER=true adds the
# sentence-transformers chain (torch etc.) and bakes the ~470MB model so the
# container starts cold-ready with no HuggingFace dependency at runtime.
# Default false — production uses the jina provider (Render's 512MB tier OOMs
# on the local model) and docker-compose runs with EMBEDDER_PREWARM=false.
# NOSONAR: requirements files are fully pinned; sdist builds are required for
# http-ece (no Linux wheel), so --only-binary is not used.
ARG WITH_LOCAL_EMBEDDER=false
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$WITH_LOCAL_EMBEDDER" = "true" ]; then \
         pip install --no-cache-dir -r requirements-embed.txt \
           --extra-index-url https://download.pytorch.org/whl/cpu \
         && python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"; \
       fi

# HF caches live under /app because the build runs as root but the runtime user
# is appuser — divergent default cache paths would force a runtime re-download;
# /app is chowned to appuser below. (Only populated when WITH_LOCAL_EMBEDDER.)
ENV HF_HOME=/app/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/app/.cache/sentence_transformers

# Copy application code and scripts
COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini .
COPY start.sh .
COPY scripts/ scripts/

# Ensure start script is executable
RUN chmod +x start.sh

# Run as an unprivileged user
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

# Run
CMD ["./start.sh"]

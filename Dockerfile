FROM python:3.11-slim

# Install OS Dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
# CPU-only torch first (avoids the ~2.5 GB CUDA download that the lock file's
# torch dependency would otherwise pull via sentence-transformers).
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch
RUN pip install --no-cache-dir -r requirements.txt

# Bake the local embedding model weights into the image so the container starts
# cold-ready with no HuggingFace dependency at runtime.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

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

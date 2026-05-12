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
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and scripts
COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini .
COPY start.sh .
COPY scripts/ scripts/

# Ensure start script is executable
RUN chmod +x start.sh

# Run
CMD ["./start.sh"]


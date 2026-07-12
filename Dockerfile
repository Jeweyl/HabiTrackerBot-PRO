FROM python:3.11-slim

ENV PYTHONPATH=/app

WORKDIR /app

# Install system dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project source code
COPY src/ ./src/
COPY alembic.ini .
COPY alembic/ ./alembic/

# Run Alembic migrations and then start the bot
CMD ["python", "src/main.py"]

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

# Debug: print env var names (no values) before migrations, then start the bot
CMD ["sh", "-c", "echo '--- Available env keys ---' && env | cut -d= -f1 | sort | tr '\n' ' ' && echo '' && echo '--- Starting migrations ---' && alembic upgrade head && python src/main.py"]

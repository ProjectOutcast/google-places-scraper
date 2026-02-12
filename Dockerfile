FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create temp directory for job files
RUN mkdir -p /app/temp

# Start with gunicorn — Railway injects PORT at runtime (must use shell form for $PORT expansion)
CMD exec gunicorn app:app --bind 0.0.0.0:${PORT:-5000} --workers 2 --threads 4 --timeout 300

# Use official lightweight Python image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies (for psycopg2 and other tools)
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Create cache directory
RUN mkdir -p .cache/flask_cache

# Expose the application port
EXPOSE 5000

# Set environment variables (fallbacks, should be overridden by .env or docker-compose)
ENV FLASK_APP=app.py
ENV FLASK_PORT=5000

# Start the application using Gunicorn for production readiness
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]

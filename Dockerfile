FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY gateway/ gateway/
COPY gateway.py .

EXPOSE 8900

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8900/health'); assert r.status_code == 200"

# Run with uvicorn (production)
CMD ["uvicorn", "gateway.api:app", "--host", "0.0.0.0", "--port", "8900", "--workers", "2"]

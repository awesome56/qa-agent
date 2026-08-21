# Dev Dockerfile — includes source for debugging
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# k6
RUN apt-get update && apt-get install -y ca-certificates gnupg curl \
  && curl -fsSL https://dl.k6.io/key.gpg | gpg --dearmor -o /usr/share/keyrings/k6-archive-keyring.gpg \
  && echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" | tee /etc/apt/sources.list.d/k6.list \
  && apt-get update && apt-get install -y k6 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# playwright browsers already in base image
ENV PYTHONUNBUFFERED=1 PORT=8000 STORAGE_DIR=/app/storage
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

FROM python:3.12-slim

# pytesseract needs the tesseract system binary (used for image OCR).
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY artifacts ./artifacts

ENV APP_ENV=production
ENV DEMO_MODE=false
EXPOSE 8000
# Render injects $PORT (e.g. 10000); default to 8000 for local/docker-compose use.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

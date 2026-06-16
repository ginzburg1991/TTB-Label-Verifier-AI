# TTB Label Verifier — container image.
# Includes the Tesseract OCR system binary (the one dependency pip can't provide).
FROM python:3.11-slim

# System dependency: Tesseract OCR engine.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better build caching).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code.
COPY . .

# Generate the sample labels into the image (optional; comment out to skip).
RUN python scripts/generate_test_labels.py || true

# Hosts (Render, Railway, Cloud Run, etc.) inject $PORT; bind to it.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

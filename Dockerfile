FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg tesseract-ocr tesseract-ocr-eng tesseract-ocr-sin ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY worker.py .
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 65534:65534
CMD ["python", "/app/worker.py", "--watch"]

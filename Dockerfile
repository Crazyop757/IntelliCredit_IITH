# ═══════════════════════════════════════════════════════════════════════════
# Intelli-Credit API — Backend Dockerfile
# Multi-stage build: deps layer (cached) → app layer (fast rebuild)
# ═══════════════════════════════════════════════════════════════════════════

FROM python:3.11-slim AS base

# System deps for pdfplumber, Tesseract OCR, ReportLab font rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Dependency layer (cached unless requirements.txt changes) ────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ─────────────────────────────────────────────────────
COPY src/ src/
COPY models/ models/
COPY configs/ configs/
COPY run_api.py .
COPY .env.example .env.example

# Create required directories
RUN mkdir -p data/raw data/bronze data/silver data/gold outputs/cam_reports

EXPOSE 8000

# Health check — Render uses this, also useful for Docker Compose
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Production start: single worker to stay within free tier RAM
CMD ["python", "run_api.py", "--workers", "1", "--log-level", "warning"]

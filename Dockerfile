# ═══════════════════════════════════════════════════════════════════════════
# Intelli-Credit — Single-container Dockerfile for Hugging Face Spaces
# Serves both the FastAPI backend AND the built frontend via FastAPI static files
# ═══════════════════════════════════════════════════════════════════════════

# ── Stage 1: Build frontend ──────────────────────────────────────────────
FROM node:18-alpine AS frontend-build
WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit

COPY frontend/ .
ENV VITE_API_URL=/api/v1
ENV VITE_API_KEY=dev-key-change-in-production

# Supabase public keys — set these as Space Variables in HF settings
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL
ENV VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY

RUN npm run build

# ── Stage 2: Python backend + serve frontend static files ────────────────
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libgl1 \
    libglib2.0-0 \
    curl \
    && curl -sSL "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.15.0/tectonic-0.15.0-x86_64-unknown-linux-musl.tar.gz" \
       | tar xz -C /usr/local/bin \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ src/
COPY models/pipeline_models.py models/pipeline_models.py
COPY scripts/ scripts/
COPY run_api.py .
COPY .env.example .env.example

# Generate a rule-based GNN placeholder (no .pt file needed in repo)
RUN python scripts/create_placeholder_gnn.py

# Download HuggingFace models at build time so they are baked into the image
RUN python scripts/download_models.py

# Point HuggingFace libraries to the baked-in cache at runtime
ENV TRANSFORMERS_CACHE=/app/configs/model_cache
ENV HF_HOME=/app/configs/model_cache

# Copy built frontend from stage 1
COPY --from=frontend-build /app/dist /app/frontend_dist

# Create data directories
RUN mkdir -p data/raw data/bronze data/silver data/gold outputs/cam_reports

# HF Spaces requires port 7860
ENV PORT=7860
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:7860/health || exit 1

CMD ["python", "run_api.py", "--workers", "1", "--log-level", "warning"]

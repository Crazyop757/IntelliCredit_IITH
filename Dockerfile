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
# API key — set VITE_API_KEY as an HF Space Variable to match INTELLI_API_KEY secret
ARG VITE_API_KEY=dev-key-change-in-production
ENV VITE_API_KEY=$VITE_API_KEY

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
# Install CPU-only PyTorch first (saves ~1.5 GB vs the default CUDA bundle,
# which OOM-kills the 16 GB HF Spaces free tier).
# torch-geometric is NOT installed — it needs C++ compilation toolchains
# absent from python:3.11-slim; the GNN detector falls back to rule-based
# scoring automatically when torch_geometric is missing.
RUN pip install --no-cache-dir \
    torch==2.6.0+cpu \
    --extra-index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# ── Download HF models BEFORE copying src/ so this layer is cached
#    independently of source-code changes. Cache is only busted when
#    requirements.txt changes (new transformers version etc.)
COPY scripts/download_hf_models.py scripts/download_hf_models.py
ENV TRANSFORMERS_CACHE=/app/configs/model_cache
ENV HF_HOME=/app/configs/model_cache
# HF_TOKEN enables authenticated model downloads (set as HF Space secret)
ARG HF_TOKEN
ENV HF_TOKEN=${HF_TOKEN}
RUN python scripts/download_hf_models.py

# ── Now copy application code (changes here won't bust the model cache)
COPY src/ src/
COPY models/pipeline_models.py models/pipeline_models.py
COPY scripts/ scripts/
COPY run_api.py .
COPY .env.example .env.example

# Generate a rule-based GNN placeholder (no .pt file needed in repo)
RUN python scripts/create_placeholder_gnn.py

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

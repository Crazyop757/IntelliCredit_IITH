"""
API-level settings — read from environment / .env.
All env vars are prefixed with  FINSIGHT_
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FINSIGHT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Security ───────────────────────────────────────────────────────
    api_key: str = Field(
        default="dev-key-change-in-production",
        validation_alias=AliasChoices("FINSIGHT_API_KEY", "INTELLI_API_KEY"),
    )
    api_key_header: str = "X-API-Key"
    # Set to True to skip key check (useful in trusted internal deployments)
    disable_auth: bool = False

    # ── CORS ───────────────────────────────────────────────────────────
    # Override in production via FINSIGHT_CORS_ORIGINS env var (JSON list)
    cors_origins: List[str] = [
        "http://localhost:3000",
        "http://localhost:8501",
        "http://localhost:8000",
        "https://finsight-frontend.onrender.com",        "https://techbriny07-finsight.hf.space",    ]

    # ── Server ─────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = int(os.environ.get("PORT", "8000"))  # Render sets PORT
    reload: bool = False
    debug: bool = False

    # ── Paths ──────────────────────────────────────────────────────────
    project_root: Path = Path(".")
    model_path: Path = Path("models/gnn_fraud_detector.pt")
    outputs_dir: Path = Path("outputs")
    data_dir: Path = Path("data")

    # ── Upstream integration ───────────────────────────────────────────
    # AliasChoices lets pydantic-settings accept BOTH the prefixed name
    # (FINSIGHT_ANTHROPIC_API_KEY) AND the plain name (ANTHROPIC_API_KEY).
    anthropic_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("FINSIGHT_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )
    tavily_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("FINSIGHT_TAVILY_API_KEY", "TAVILY_API_KEY"),
    )
    serpapi_key: str = Field(
        default="",
        validation_alias=AliasChoices("FINSIGHT_SERPAPI_KEY", "SERPAPI_KEY"),
    )

    # ── Background workers ─────────────────────────────────────────
    # Max threads in the executor for sync-heavy pipeline tasks
    max_pipeline_workers: int = 4
    # Max jobs kept in memory (oldest evicted when exceeded)
    job_store_max_size: int = 500

    # ── File upload limits (bytes) ─────────────────────────────────
    max_pdf_size: int = 50 * 1024 * 1024     # 50 MB
    max_bank_csv_size: int = 10 * 1024 * 1024  # 10 MB
    max_gst_json_size: int = 5 * 1024 * 1024   # 5 MB

    # ── Supabase ───────────────────────────────────────────────────
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""

    # ── Environment ────────────────────────────────────────────────
    env: str = "development"

    @field_validator("outputs_dir", "data_dir", mode="before")
    @classmethod
    def _ensure_path(cls, v: str | Path) -> Path:
        p = Path(v)
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = APISettings()

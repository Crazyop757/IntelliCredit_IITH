"""
Supabase client factory.

- `get_supabase_client()`       — anon/user-facing client (respects RLS)
- `get_supabase_admin_client()` — service-role client (bypasses RLS, backend-only)
"""
from __future__ import annotations

import logging
from functools import lru_cache

log = logging.getLogger(__name__)

_client = None
_admin_client = None


def get_supabase_client():
    """Return a cached anonymous Supabase client (respects RLS)."""
    global _client
    if _client is not None:
        return _client
    from src.api.config import settings
    if not settings.supabase_url or not settings.supabase_anon_key:
        log.warning("Supabase URL/anon key not configured — database persistence disabled.")
        return None
    try:
        from supabase import create_client
        _client = create_client(settings.supabase_url, settings.supabase_anon_key)
        return _client
    except Exception as exc:
        log.error("Failed to create Supabase client: %s", exc)
        return None


def get_supabase_admin_client():
    """Return a cached service-role Supabase client (bypasses RLS, backend-only)."""
    global _admin_client
    if _admin_client is not None:
        return _admin_client
    from src.api.config import settings
    if not settings.supabase_url or not settings.supabase_service_role_key:
        log.warning("Supabase URL/service role key not configured — admin client unavailable.")
        return None
    try:
        from supabase import create_client
        _admin_client = create_client(settings.supabase_url, settings.supabase_service_role_key)
        return _admin_client
    except Exception as exc:
        log.error("Failed to create Supabase admin client: %s", exc)
        return None

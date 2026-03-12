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
_client_failed = False
_admin_client = None
_admin_client_failed = False


def get_supabase_client():
    """Return a cached anonymous Supabase client (respects RLS)."""
    global _client, _client_failed
    if _client is not None:
        return _client
    if _client_failed:
        return None
    from src.api.config import settings
    if not settings.supabase_url or not settings.supabase_anon_key:
        log.warning("Supabase URL/anon key not configured — database persistence disabled.")
        _client_failed = True
        return None
    if not settings.supabase_url.startswith("https://"):
        log.error("Supabase URL must start with https:// — got %r. Database disabled.", settings.supabase_url)
        _client_failed = True
        return None
    try:
        from supabase import create_client
        _client = create_client(settings.supabase_url, settings.supabase_anon_key)
        log.info("Supabase anon client initialised.")
        return _client
    except Exception as exc:
        log.error("Failed to create Supabase client: %s", exc, exc_info=True)
        _client_failed = True
        return None


def get_supabase_admin_client():
    """Return a cached service-role Supabase client (bypasses RLS, backend-only)."""
    global _admin_client, _admin_client_failed
    if _admin_client is not None:
        return _admin_client
    if _admin_client_failed:
        return None
    from src.api.config import settings
    if not settings.supabase_url or not settings.supabase_service_role_key:
        log.warning("Supabase URL/service role key not configured — admin client unavailable.")
        _admin_client_failed = True
        return None
    if not settings.supabase_url.startswith("https://"):
        log.error("Supabase URL must start with https:// — admin client disabled.")
        _admin_client_failed = True
        return None
    try:
        from supabase import create_client
        _admin_client = create_client(settings.supabase_url, settings.supabase_service_role_key)
        log.info("Supabase admin client initialised.")
        return _admin_client
    except Exception as exc:
        log.error("Failed to create Supabase admin client: %s", exc, exc_info=True)
        _admin_client_failed = True
        return None

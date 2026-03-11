"""
Auth router — profile management endpoints.
Supabase handles sign-up/sign-in/password-reset directly on the client side.
This router exposes backend-only operations (profile read/update).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from src.api.dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class ProfileResponse(BaseModel):
    id: str
    email: str | None
    full_name: str | None
    avatar_url: str | None
    role: str | None


class ProfileUpdateRequest(BaseModel):
    full_name: str | None = None
    avatar_url: str | None = None


@router.get("/me", response_model=ProfileResponse, summary="Get current user profile")
async def get_me(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> ProfileResponse:
    meta = current_user.get("user_metadata") or {}
    return ProfileResponse(
        id=current_user.get("sub", ""),
        email=current_user.get("email"),
        full_name=meta.get("full_name"),
        avatar_url=meta.get("avatar_url"),
        role=current_user.get("role"),
    )


@router.patch("/profile", response_model=ProfileResponse, summary="Update user profile metadata")
async def update_profile(
    body: ProfileUpdateRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
) -> ProfileResponse:
    from src.database.supabase_client import get_supabase_admin_client
    db = get_supabase_admin_client()
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured.",
        )
    user_id = current_user.get("sub")
    updates: dict = {}
    if body.full_name is not None:
        updates["full_name"] = body.full_name
    if body.avatar_url is not None:
        updates["avatar_url"] = body.avatar_url

    if updates:
        try:
            db.auth.admin.update_user_by_id(user_id, {"user_metadata": updates})
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update profile: {exc}",
            )

    merged_meta = {**(current_user.get("user_metadata") or {}), **updates}
    return ProfileResponse(
        id=user_id or "",
        email=current_user.get("email"),
        full_name=merged_meta.get("full_name"),
        avatar_url=merged_meta.get("avatar_url"),
        role=current_user.get("role"),
    )

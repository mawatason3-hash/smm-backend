from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from datetime import datetime, timedelta, timezone
from database import get_db
from models.user import User, RefreshToken, PasswordResetToken
from models.transaction import Transaction
from schemas.auth import (
    RegisterRequest, LoginRequest, TokenResponse, RefreshRequest,
    ForgotPasswordRequest, ResetPasswordRequest, ChangePasswordRequest,
    UpdateProfileRequest, UserResponse
)
from utils.security import (
    hash_password, verify_password, create_access_token,
    create_refresh_token, hash_token, decode_access_token,
    generate_referral_code, generate_api_key
)
from middleware.auth_middleware import get_current_user
from config import settings
from services.notification_service import send_email
import uuid
import secrets

router = APIRouter(prefix="/api/auth", tags=["auth"])

@router.post("/register", response_model=TokenResponse)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Check email exists
    result = await db.execute(select(User).where(User.email == data.email.lower()))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Check referral code
    referrer_id = None
    if data.referral_code:
        ref_result = await db.execute(select(User).where(User.referral_code == data.referral_code.upper()))
        referrer = ref_result.scalar_one_or_none()
        if referrer:
            referrer_id = referrer.id

    # Create user
    user = User(
        email=data.email.lower(),
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        phone=data.phone,
        country=data.country,
        referral_code=generate_referral_code(),
        referred_by=referrer_id,
        api_key=generate_api_key(),
        balance=0.00,
    )
    db.add(user)
    await db.flush()

    # Create tokens
    access_token = create_access_token({"sub": str(user.id), "role": user.role})
    raw_refresh, hashed_refresh = create_refresh_token()

    refresh_token_obj = RefreshToken(
        user_id=user.id,
        token_hash=hashed_refresh,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    db.add(refresh_token_obj)
    await db.commit()

    return TokenResponse(access_token=access_token, refresh_token=raw_refresh)

@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email.lower()))
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if user.status in ["suspended", "banned"]:
        raise HTTPException(status_code=403, detail=f"Account is {user.status}")

    # Update last login
    user.last_login_at = datetime.now(timezone.utc)

    access_token = create_access_token({"sub": str(user.id), "role": user.role})
    raw_refresh, hashed_refresh = create_refresh_token()

    refresh_token_obj = RefreshToken(
        user_id=user.id,
        token_hash=hashed_refresh,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    db.add(refresh_token_obj)
    await db.commit()

    return TokenResponse(access_token=access_token, refresh_token=raw_refresh)

@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    token_hash = hash_token(data.refresh_token)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at == None,
            RefreshToken.expires_at > now
        )
    )
    token_obj = result.scalar_one_or_none()

    if not token_obj:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    # Get user
    user_result = await db.execute(select(User).where(User.id == token_obj.user_id))
    user = user_result.scalar_one_or_none()

    if not user or user.status in ["suspended", "banned"]:
        raise HTTPException(status_code=401, detail="User unavailable")

    # Revoke old, issue new
    token_obj.revoked_at = now
    access_token = create_access_token({"sub": str(user.id), "role": user.role})
    raw_refresh, hashed_refresh = create_refresh_token()

    new_refresh = RefreshToken(
        user_id=user.id,
        token_hash=hashed_refresh,
        expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    db.add(new_refresh)
    await db.commit()

    return TokenResponse(access_token=access_token, refresh_token=raw_refresh)

@router.post("/logout")
async def logout(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    token_hash = hash_token(data.refresh_token)
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    token_obj = result.scalar_one_or_none()

    if token_obj:
        token_obj.revoked_at = datetime.now(timezone.utc)
        await db.commit()

    return {"message": "Logged out successfully"}

@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "full_name": current_user.full_name,
        "phone": current_user.phone,
        "country": current_user.country,
        "role": current_user.role,
        "status": current_user.status,
        "balance": float(current_user.balance),
        "referral_code": current_user.referral_code,
        "is_developer": current_user.is_developer,
        "api_key": current_user.api_key if current_user.is_developer else None,
        "admin_power_used": current_user.admin_power_used,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
    }

@router.put("/me")
async def update_me(
    data: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if data.full_name:
        current_user.full_name = data.full_name
    if data.phone is not None:
        current_user.phone = data.phone
    if data.country is not None:
        current_user.country = data.country

    await db.commit()
    return {"message": "Profile updated successfully"}

@router.put("/change-password")
async def change_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not verify_password(data.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    current_user.password_hash = hash_password(data.new_password)
    await db.commit()
    return {"message": "Password changed successfully"}

@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email.lower()))
    user = result.scalar_one_or_none()

    # Always return success to prevent email enumeration
    if user:
        token = secrets.token_urlsafe(32)
        reset_token = PasswordResetToken(
            user_id=user.id,
            token=token,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
        )
        db.add(reset_token)
        await db.commit()

        reset_url = f"{settings.FRONTEND_URL.rstrip('/')}/auth/reset-password?token={token}"
        html = f"""
        <p>Hello,</p>
        <p>You requested a password reset for your BOASTLIB account.</p>
        <p><a href="{reset_url}">Reset your password</a></p>
        <p>This link expires in 1 hour.</p>
        <p>If you did not request this, you can ignore this email.</p>
        """
        email_sent = await send_email(user.email, "Reset your BOASTLIB password", html)
        if not email_sent:
            print(f"Password reset email failed for {user.email}. Check BREVO_API_KEY and verified sender email.")

    return {"message": "If that email exists, a reset link has been sent"}

@router.post("/reset-password")
async def reset_password(data: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token == data.token,
            PasswordResetToken.used_at == None,
            PasswordResetToken.expires_at > now
        )
    )
    token_obj = result.scalar_one_or_none()

    if not token_obj:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user_result = await db.execute(select(User).where(User.id == token_obj.user_id))
    user = user_result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = hash_password(data.new_password)
    token_obj.used_at = now
    await db.commit()

    return {"message": "Password reset successfully"}

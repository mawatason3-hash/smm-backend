from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone
from typing import Optional
import secrets
import hashlib
import string
import random
from config import settings

# Use bcrypt_sha256 which pre-hashes long passwords with SHA-256
# This avoids the 72-byte limitation of raw bcrypt and prevents
# backend detection/wrapping issues on some platforms.
# Use PBKDF2-SHA256 as a robust, pure-Python fallback that avoids bcrypt
# backend/platform-specific issues and the 72-byte bcrypt limit.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def create_refresh_token() -> tuple[str, str]:
    """Returns (raw_token, hashed_token)"""
    raw = secrets.token_urlsafe(64)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None

def generate_referral_code() -> str:
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=8))

def generate_api_key() -> str:
    return "sk_live_" + secrets.token_urlsafe(32)

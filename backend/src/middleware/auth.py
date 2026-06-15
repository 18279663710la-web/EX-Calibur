from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from ..config import get_settings

security = HTTPBearer(auto_error=False)


def create_token(sub: str, username: str, role: str, expires_delta: int) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + timedelta(seconds=expires_delta),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(sub: str, username: str, role: str) -> str:
    settings = get_settings()
    return create_token(sub, username, role, settings.access_token_expire_seconds)


def create_refresh_token(sub: str, username: str, role: str) -> str:
    settings = get_settings()
    return create_token(sub, username, role, settings.refresh_token_expire_seconds)


def decode_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="缺少认证 Token")
    return decode_token(credentials.credentials)

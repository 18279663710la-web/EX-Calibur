from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..config import get_settings
from ..database import get_pool
from ..middleware.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
)
from ..models import Envelope

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8, max_length=64)
    confirm_password: str = Field(..., min_length=8, max_length=64)


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/login")
async def login(body: LoginRequest):
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id, username, email, password_hash, role, avatar_url, is_active FROM users WHERE username = $1",
        body.username,
    )
    if not row or not row["is_active"]:
        return Envelope.error(40101, "用户名或密码错误")

    async with pool.acquire() as conn:
        match = await conn.fetchval(
            "SELECT password_hash = crypt($1, password_hash) FROM users WHERE username = $2",
            body.password, body.username,
        )

    if not match:
        return Envelope.error(40101, "用户名或密码错误")

    user_id = str(row["id"])
    username = row["username"]
    role = row["role"]

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET last_login_at = NOW() WHERE id = $1", user_id
        )

    settings = get_settings()

    return Envelope.success(
        data={
            "access_token": create_access_token(user_id, username, role),
            "refresh_token": create_refresh_token(user_id, username, role),
            "token_type": "Bearer",
            "expires_in": settings.access_token_expire_seconds,
            "user": {
                "id": user_id,
                "username": username,
                "email": row["email"],
                "avatar_url": row["avatar_url"],
                "role": role,
            },
        },
        message="登录成功",
    )


@router.post("/register")
async def register(body: RegisterRequest):
    if body.password != body.confirm_password:
        return Envelope.error(40001, "两次输入的密码不一致")

    pool = await get_pool()

    existing = await pool.fetchrow("SELECT id FROM users WHERE username = $1", body.username)
    if existing:
        return Envelope.error(40901, "用户名已被占用")

    existing_email = await pool.fetchrow("SELECT id FROM users WHERE email = $1", body.email)
    if existing_email:
        return Envelope.error(40901, "邮箱已被注册")

    user_id = "00000000-0000-0000-0000-000000000009"

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO users (username, email, password_hash, role)
               VALUES ($1, $2, crypt($3, gen_salt('bf', 10)), 'user')
               RETURNING id, username, email, role, avatar_url, created_at""",
            body.username, body.email, body.password,
        )
        if row:
            user_id = str(row["id"])
            username = row["username"]
            email = row["email"]
            role = row["role"]
            avatar = row["avatar_url"]
            created_at_val = row["created_at"].isoformat() if row["created_at"] else ""
        else:
            return Envelope.error(50001, "注册失败")

    return Envelope.success(
        data={
            "id": user_id,
            "username": username,
            "email": email,
            "avatar_url": avatar,
            "role": role,
            "created_at": created_at_val,
        },
        message="注册成功",
        code=201,
    )


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    pool = await get_pool()
    row = await pool.fetchrow(
        """SELECT id, username, email, avatar_url, role,
                  quota_used_bytes, quota_total_bytes, created_at, last_login_at
           FROM users WHERE id = $1""",
        current_user["sub"],
    )
    if not row:
        return Envelope.error(40401, "用户不存在")

    return Envelope.success(data={
        "id": str(row["id"]),
        "username": row["username"],
        "email": row["email"],
        "avatar_url": row["avatar_url"],
        "role": row["role"],
        "quota_used_bytes": row["quota_used_bytes"],
        "quota_total_bytes": row["quota_total_bytes"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else "",
        "last_login_at": row["last_login_at"].isoformat() if row["last_login_at"] else None,
    })


@router.post("/refresh")
async def refresh(body: RefreshRequest):
    try:
        payload = decode_token(body.refresh_token)
    except Exception:
        return Envelope.error(40102, "Refresh Token 无效或已过期")

    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id, username, role FROM users WHERE id = $1 AND is_active = TRUE",
        payload["sub"],
    )
    if not row:
        return Envelope.error(40102, "用户不存在或已禁用")

    settings = get_settings()

    return Envelope.success(data={
        "access_token": create_access_token(str(row["id"]), row["username"], row["role"]),
        "refresh_token": create_refresh_token(str(row["id"]), row["username"], row["role"]),
        "token_type": "Bearer",
        "expires_in": settings.access_token_expire_seconds,
    })

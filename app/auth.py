import os
import time
import bcrypt
import jwt
from typing import Optional
from fastapi import Request, HTTPException, Depends
from dotenv import load_dotenv

from . import db

load_dotenv("/opt/mailhub/.env")
load_dotenv(os.path.join(os.getcwd(), ".env"))
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_COOKIE = os.environ.get("JWT_COOKIE_NAME", "mailhub_session")
JWT_TTL = 60 * 60 * 24 * 14  # 14 天


def cookie_secure_for_request(request: Request) -> bool:
    explicit = os.environ.get("COOKIE_SECURE")
    if explicit is not None:
        return explicit.lower() in ("1", "true", "yes", "on")
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    if forwarded_proto:
        return forwarded_proto.split(",", 1)[0].strip() == "https"
    return request.url.scheme == "https"


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


def make_token(user_id: int, username: str, role: str) -> str:
    now = int(time.time())
    payload = {"uid": user_id, "u": username, "r": role, "iat": now, "exp": now + JWT_TTL}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except Exception:
        return None


def get_current_user(request: Request) -> dict:
    token = request.cookies.get(JWT_COOKIE)
    if not token:
        raise HTTPException(401, "未登录")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(401, "登录已过期")
    user = db.fetchone(
        "SELECT id, username, display_name, email, role, active FROM users WHERE id=%s",
        (payload["uid"],),
    )
    if not user or not user["active"]:
        raise HTTPException(401, "账号无效")
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user

from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

from .. import auth as authmod, db
from ..config_store import ensure_self_host_schema, get_app_config, set_app_config

router = APIRouter(prefix="/api/setup", tags=["setup"])


class InitialAdminIn(BaseModel):
    username: str
    password: str
    email: EmailStr
    display_name: str | None = None
    public_base_url: str = "http://localhost:3024"
    inbound_host: str | None = None


def _users_count() -> int:
    row = db.fetchone("SELECT count(*)::int AS c FROM users")
    return int(row["c"] if row else 0)


@router.get("/status")
def setup_status():
    ensure_self_host_schema()
    users = _users_count()
    paths = []
    for env_name, default in (
        ("RAW_DIR", "/opt/mailhub/raw"),
        ("LOG_DIR", "/opt/mailhub/logs"),
        ("MAILHUB_UPLOAD_DIR", "/opt/mailhub/uploads/outbound"),
    ):
        p = Path(os.environ.get(env_name, default))
        paths.append({"name": env_name, "path": str(p), "exists": p.exists(), "writable": p.exists() and os.access(p, os.W_OK)})
    return {
        "needs_setup": users == 0,
        "users_count": users,
        "app": get_app_config(),
        "paths": paths,
        "jwt_configured": bool(os.environ.get("JWT_SECRET")),
    }


@router.post("/admin")
def create_initial_admin(body: InitialAdminIn):
    ensure_self_host_schema()
    if _users_count() > 0:
        raise HTTPException(409, "系统已经初始化")
    if len(body.password) < 10:
        raise HTTPException(400, "管理员密码至少 10 位")
    username = body.username.strip()
    if not username:
        raise HTTPException(400, "用户名不能为空")
    hashed = authmod.hash_password(body.password)
    db.execute(
        """
        INSERT INTO users (username, password_hash, display_name, email, role, active)
        VALUES (%s,%s,%s,%s,'admin',true)
        """,
        (username, hashed, body.display_name or username, str(body.email).lower()),
    )
    host = body.inbound_host or body.public_base_url.replace("https://", "").replace("http://", "").split("/", 1)[0]
    set_app_config(
        {
            "app_name": "Mailhub",
            "public_base_url": body.public_base_url.rstrip("/"),
            "inbound_host": host,
            "install_id": secrets.token_hex(8),
        }
    )
    return {"ok": True}

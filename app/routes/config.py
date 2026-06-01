import imaplib
import os
import subprocess
import smtplib
import socket
import ssl
import sys
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from .. import db, auth as authmod, tg
from ..config_store import ensure_self_host_schema, get_app_config, set_app_config

router = APIRouter(prefix="/api/config", tags=["config"])


def _mask_secret(value: str | None) -> str:
    value = value or ""
    if len(value) <= 8:
        return "***" if value else ""
    return f"{value[:4]}...{value[-4:]}"


def _keep_existing_secret(table: str, column: str, incoming: str | None) -> str | None:
    if incoming and not incoming.startswith("***"):
        return incoming
    row = db.fetchone(f"SELECT {column} FROM {table} WHERE id=1")
    return row[column] if row else incoming


def _host_from_url(url: str | None) -> str:
    parsed = urlparse(url or "")
    return parsed.hostname or (url or "").split("/", 1)[0] or "mail.example.com"


# ===== AI =====
class AIConfigIn(BaseModel):
    provider: str            # openai | anthropic
    endpoint: str
    api_key: Optional[str] = None
    model: str
    system_prompt: Optional[str] = None
    enabled: bool = True


@router.get("/ai")
def get_ai(user: dict = Depends(authmod.get_current_user)):
    ensure_self_host_schema()
    row = db.fetchone("SELECT provider, endpoint, api_key, model, system_prompt, enabled, updated_at FROM ai_config WHERE id=1")
    if row:
        row["api_key_masked"] = _mask_secret(row.get("api_key"))
        row.pop("api_key", None)
    return row


@router.put("/ai")
def set_ai(body: AIConfigIn, user: dict = Depends(authmod.require_admin)):
    ensure_self_host_schema()
    if body.provider not in ("openai", "anthropic"):
        raise HTTPException(400, "provider 必须是 openai 或 anthropic")
    api_key = _keep_existing_secret("ai_config", "api_key", body.api_key) or ""
    if body.enabled and not api_key:
        raise HTTPException(400, "启用 AI 时必须填写 API Key")
    db.execute(
        """INSERT INTO ai_config (id, provider, endpoint, api_key, model, system_prompt, enabled, updated_at)
           VALUES (1, %s, %s, %s, %s, %s, %s, now())
           ON CONFLICT (id) DO UPDATE SET
             provider=EXCLUDED.provider, endpoint=EXCLUDED.endpoint, api_key=EXCLUDED.api_key,
             model=EXCLUDED.model, system_prompt=EXCLUDED.system_prompt, enabled=EXCLUDED.enabled,
             updated_at=now()""",
        (body.provider, body.endpoint, api_key, body.model, body.system_prompt, body.enabled),
    )
    return {"ok": True}


# ===== TG =====
class TGConfigIn(BaseModel):
    bot_token: Optional[str] = None
    chat_id: str
    push_min_priority: str = "high"
    enabled: bool = True


@router.get("/tg")
def get_tg(user: dict = Depends(authmod.get_current_user)):
    ensure_self_host_schema()
    row = db.fetchone("SELECT bot_token, chat_id, push_min_priority, enabled, updated_at FROM tg_config WHERE id=1")
    if row:
        row["bot_token_masked"] = _mask_secret(row.get("bot_token"))
        row.pop("bot_token", None)
    return row


@router.put("/tg")
def set_tg(body: TGConfigIn, user: dict = Depends(authmod.require_admin)):
    ensure_self_host_schema()
    bot_token = _keep_existing_secret("tg_config", "bot_token", body.bot_token)
    if body.enabled and not bot_token:
        raise HTTPException(400, "启用 Telegram 推送时必须填写 Bot Token")
    db.execute(
        """INSERT INTO tg_config (id, bot_token, chat_id, push_min_priority, enabled, updated_at)
           VALUES (1, %s, %s, %s, %s, now())
           ON CONFLICT (id) DO UPDATE SET
             bot_token=EXCLUDED.bot_token, chat_id=EXCLUDED.chat_id,
             push_min_priority=EXCLUDED.push_min_priority, enabled=EXCLUDED.enabled, updated_at=now()""",
        (bot_token, body.chat_id, body.push_min_priority, body.enabled),
    )
    return {"ok": True}


@router.post("/tg/test")
def test_tg(user: dict = Depends(authmod.require_admin)):
    ok = tg.push_sync("🟢 mailhub TG 测试推送 — 收到这条说明配置 OK")
    return {"ok": ok}


# ===== App / SMTP / IMAP / diagnostics =====
class AppConfigIn(BaseModel):
    app_name: str = "Mailhub"
    public_base_url: str
    inbound_host: Optional[str] = None
    default_timezone: str = "UTC"


@router.get("/app")
def get_app(user: dict = Depends(authmod.get_current_user)):
    ensure_self_host_schema()
    return get_app_config()


@router.put("/app")
def set_app(body: AppConfigIn, user: dict = Depends(authmod.require_admin)):
    ensure_self_host_schema()
    set_app_config(
        {
            "app_name": body.app_name.strip() or "Mailhub",
            "public_base_url": body.public_base_url.rstrip("/"),
            "inbound_host": (body.inbound_host or _host_from_url(body.public_base_url)).strip(),
            "default_timezone": body.default_timezone.strip() or "UTC",
        }
    )
    return {"ok": True}


class SMTPConfigIn(BaseModel):
    mode: str = "local_postfix"
    host: Optional[str] = None
    port: int = 587
    username: Optional[str] = None
    password: Optional[str] = None
    use_tls: bool = False
    use_starttls: bool = True
    enabled: bool = True


@router.get("/smtp")
def get_smtp(user: dict = Depends(authmod.get_current_user)):
    ensure_self_host_schema()
    row = db.fetchone(
        "SELECT mode, host, port, username, password, use_tls, use_starttls, enabled, updated_at FROM smtp_config WHERE id=1"
    )
    if not row:
        return {
            "mode": "local_postfix",
            "port": 587,
            "use_tls": False,
            "use_starttls": True,
            "enabled": True,
            "password_masked": "",
        }
    row["password_masked"] = _mask_secret(row.get("password"))
    row.pop("password", None)
    return row


@router.put("/smtp")
def set_smtp(body: SMTPConfigIn, user: dict = Depends(authmod.require_admin)):
    ensure_self_host_schema()
    if body.mode not in ("local_postfix", "smtp"):
        raise HTTPException(400, "mode 必须是 local_postfix 或 smtp")
    password = _keep_existing_secret("smtp_config", "password", body.password)
    if body.mode == "smtp" and body.enabled and (not body.host or not body.port):
        raise HTTPException(400, "SMTP 模式必须填写 host 和 port")
    db.execute(
        """INSERT INTO smtp_config
           (id, mode, host, port, username, password, use_tls, use_starttls, enabled, updated_at)
           VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, now())
           ON CONFLICT (id) DO UPDATE SET
             mode=EXCLUDED.mode, host=EXCLUDED.host, port=EXCLUDED.port,
             username=EXCLUDED.username, password=EXCLUDED.password,
             use_tls=EXCLUDED.use_tls, use_starttls=EXCLUDED.use_starttls,
             enabled=EXCLUDED.enabled, updated_at=now()""",
        (
            body.mode,
            body.host,
            body.port,
            body.username,
            password,
            body.use_tls,
            body.use_starttls,
            body.enabled,
        ),
    )
    return {"ok": True}


@router.post("/smtp/test")
def test_smtp(user: dict = Depends(authmod.require_admin)):
    ensure_self_host_schema()
    cfg = db.fetchone("SELECT * FROM smtp_config WHERE id=1")
    if not cfg or cfg.get("mode") == "local_postfix":
        try:
            with smtplib.SMTP("127.0.0.1", 25, timeout=10) as s:
                s.ehlo()
            return {"ok": True, "message": "本机 Postfix 可连接"}
        except Exception as e:
            return {"ok": False, "message": repr(e)}
    try:
        if cfg.get("use_tls"):
            client = smtplib.SMTP_SSL(cfg["host"], int(cfg["port"]), timeout=20, context=ssl.create_default_context())
        else:
            client = smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=20)
        with client as s:
            s.ehlo()
            if cfg.get("use_starttls") and not cfg.get("use_tls"):
                s.starttls(context=ssl.create_default_context())
                s.ehlo()
            if cfg.get("username"):
                s.login(cfg["username"], cfg.get("password") or "")
        return {"ok": True, "message": "SMTP 登录成功"}
    except Exception as e:
        return {"ok": False, "message": repr(e)}


class IMAPAccountIn(BaseModel):
    label: str
    host: str
    port: int = 993
    username: str
    password: Optional[str] = None
    mailbox: str = "INBOX"
    use_ssl: bool = True
    enabled: bool = True
    source: Optional[str] = None


def _imap_row(row: dict) -> dict:
    row["password_masked"] = _mask_secret(row.get("password"))
    row.pop("password", None)
    return row


@router.get("/imap")
def list_imap(user: dict = Depends(authmod.require_admin)):
    ensure_self_host_schema()
    rows = db.fetchall(
        """SELECT id, label, host, port, username, password, mailbox, use_ssl,
                  enabled, source, last_uid, last_sync_at, last_error, updated_at
           FROM imap_accounts ORDER BY enabled DESC, id"""
    )
    return [_imap_row(r) for r in rows]


@router.post("/imap")
def create_imap(body: IMAPAccountIn, user: dict = Depends(authmod.require_admin)):
    ensure_self_host_schema()
    if not body.password:
        raise HTTPException(400, "新增 IMAP 账号必须填写密码或应用专用密码")
    row = db.execute_returning(
        """INSERT INTO imap_accounts
           (label, host, port, username, password, mailbox, use_ssl, enabled, source, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
           RETURNING id""",
        (
            body.label.strip(),
            body.host.strip(),
            body.port,
            body.username.strip(),
            body.password,
            body.mailbox.strip() or "INBOX",
            body.use_ssl,
            body.enabled,
            body.source or body.label.strip(),
        ),
    )
    return {"id": row["id"]}


@router.put("/imap/{account_id}")
def update_imap(account_id: int, body: IMAPAccountIn, user: dict = Depends(authmod.require_admin)):
    ensure_self_host_schema()
    current = db.fetchone("SELECT password FROM imap_accounts WHERE id=%s", (account_id,))
    if not current:
        raise HTTPException(404, "IMAP 账号不存在")
    password = body.password if body.password and not body.password.startswith("***") else current["password"]
    db.execute(
        """UPDATE imap_accounts
           SET label=%s, host=%s, port=%s, username=%s, password=%s, mailbox=%s,
               use_ssl=%s, enabled=%s, source=%s, updated_at=now()
           WHERE id=%s""",
        (
            body.label.strip(),
            body.host.strip(),
            body.port,
            body.username.strip(),
            password,
            body.mailbox.strip() or "INBOX",
            body.use_ssl,
            body.enabled,
            body.source or body.label.strip(),
            account_id,
        ),
    )
    return {"ok": True}


@router.delete("/imap/{account_id}")
def delete_imap(account_id: int, user: dict = Depends(authmod.require_admin)):
    ensure_self_host_schema()
    db.execute("DELETE FROM imap_accounts WHERE id=%s", (account_id,))
    return {"ok": True}


def _test_imap_login(row: dict) -> tuple[bool, str]:
    try:
        if row.get("use_ssl"):
            client = imaplib.IMAP4_SSL(row["host"], int(row["port"]), timeout=20)
        else:
            client = imaplib.IMAP4(row["host"], int(row["port"]), timeout=20)
        with client as imap:
            imap.login(row["username"], row["password"])
            typ, _ = imap.select(row.get("mailbox") or "INBOX", readonly=True)
            if typ != "OK":
                return False, "登录成功但 mailbox 打不开"
        return True, "IMAP 登录成功"
    except Exception as e:
        return False, repr(e)


@router.post("/imap/{account_id}/test")
def test_imap(account_id: int, user: dict = Depends(authmod.require_admin)):
    ensure_self_host_schema()
    row = db.fetchone("SELECT * FROM imap_accounts WHERE id=%s", (account_id,))
    if not row:
        raise HTTPException(404, "IMAP 账号不存在")
    ok, message = _test_imap_login(row)
    return {"ok": ok, "message": message}


@router.post("/imap/{account_id}/sync")
def sync_imap_now(account_id: int, user: dict = Depends(authmod.require_admin)):
    ensure_self_host_schema()
    row = db.fetchone("SELECT id FROM imap_accounts WHERE id=%s", (account_id,))
    if not row:
        raise HTTPException(404, "IMAP 账号不存在")
    root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [os.environ.get("PYTHON", sys.executable), str(root / "bin" / "imap_sync.py"), "--account-id", str(account_id), "--limit", "50"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=180,
    )
    return {"ok": proc.returncode == 0, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]}


@router.get("/diagnostics")
def diagnostics(user: dict = Depends(authmod.require_admin)):
    ensure_self_host_schema()
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str):
        checks.append({"name": name, "ok": ok, "detail": detail})

    try:
        db.fetchone("SELECT 1 AS ok")
        add("database", True, "Postgres 可连接")
    except Exception as e:
        add("database", False, repr(e))

    for label, env_name, default in (
        ("raw_dir", "RAW_DIR", "/opt/mailhub/raw"),
        ("log_dir", "LOG_DIR", "/opt/mailhub/logs"),
        ("upload_dir", "MAILHUB_UPLOAD_DIR", "/opt/mailhub/uploads/outbound"),
    ):
        path = Path(os.environ.get(env_name, default))
        add(label, path.exists() and os.access(path, os.W_OK), f"{path} {'可写' if path.exists() else '不存在'}")

    try:
        s = socket.create_connection(("127.0.0.1", 25), timeout=2)
        s.close()
        add("local_postfix", True, "127.0.0.1:25 可连接")
    except Exception as e:
        add("local_postfix", False, repr(e))

    counts = {
        "users": db.fetchone("SELECT count(*)::int AS c FROM users")["c"],
        "domains": db.fetchone("SELECT count(*)::int AS c FROM domains")["c"],
        "senders": db.fetchone("SELECT count(*)::int AS c FROM senders")["c"],
        "imap_accounts": db.fetchone("SELECT count(*)::int AS c FROM imap_accounts")["c"],
        "queued_ai_jobs": db.fetchone("SELECT count(*)::int AS c FROM ai_jobs WHERE status IN ('queued','running')")["c"],
    }
    return {"checks": checks, "counts": counts, "app": get_app_config()}


# ===== Users =====
class UserIn(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    role: str = "user"


@router.get("/users")
def list_users(user: dict = Depends(authmod.require_admin)):
    return db.fetchall(
        "SELECT id, username, display_name, email, role, active, created_at, last_login_at FROM users ORDER BY id"
    )


@router.post("/users")
def create_user(body: UserIn, user: dict = Depends(authmod.require_admin)):
    if body.role not in ("admin", "user"):
        raise HTTPException(400, "role 必须是 admin 或 user")
    hashed = authmod.hash_password(body.password)
    row = db.execute_returning(
        "INSERT INTO users (username, password_hash, display_name, email, role) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (body.username, hashed, body.display_name, body.email, body.role),
    )
    return {"id": row["id"]}


class PasswordIn(BaseModel):
    new_password: str


@router.post("/users/{uid}/password")
def reset_password(uid: int, body: PasswordIn, user: dict = Depends(authmod.require_admin)):
    hashed = authmod.hash_password(body.new_password)
    db.execute("UPDATE users SET password_hash=%s WHERE id=%s", (hashed, uid))
    return {"ok": True}


@router.delete("/users/{uid}")
def delete_user(uid: int, user: dict = Depends(authmod.require_admin)):
    if uid == user["id"]:
        raise HTTPException(400, "不能删除自己")
    db.execute("UPDATE users SET active=false WHERE id=%s", (uid,))
    return {"ok": True}

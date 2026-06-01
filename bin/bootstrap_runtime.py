#!/usr/bin/env python3
"""Apply schema and seed first-run settings for Docker/self-host installs."""
from __future__ import annotations

import os
import secrets
import sys
import time
from pathlib import Path

import bcrypt
import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv("/opt/mailhub/.env")


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value


DATABASE_URL = env("DATABASE_URL")


def connect_with_retry():
    last = None
    for _ in range(40):
        try:
            return psycopg.connect(DATABASE_URL, row_factory=dict_row)
        except Exception as e:
            last = e
            time.sleep(1)
    raise RuntimeError(f"Database not ready: {last!r}")


def apply_schema(conn) -> None:
    sql = (ROOT / "schema.sql").read_text()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def set_app_config(conn, key: str, value: str | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO app_config (key, value, updated_at)
            VALUES (%s,%s,now())
            ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()
            """,
            (key, value),
        )
    conn.commit()


def seed_admin(conn) -> None:
    admin_user = os.environ.get("MAILHUB_ADMIN_USERNAME", "admin")
    admin_password = os.environ.get("MAILHUB_ADMIN_PASSWORD")
    admin_email = os.environ.get("MAILHUB_ADMIN_EMAIL", "admin@example.com")
    display = os.environ.get("MAILHUB_ADMIN_DISPLAY_NAME", "Administrator")
    with conn.cursor() as cur:
        cur.execute("SELECT count(*)::int AS c FROM users")
        users = cur.fetchone()["c"]
    if users > 0 or not admin_password:
        return
    hashed = bcrypt.hashpw(admin_password.encode(), bcrypt.gensalt()).decode()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (username, password_hash, display_name, email, role, active)
            VALUES (%s,%s,%s,%s,'admin',true)
            """,
            (admin_user, hashed, display, admin_email),
        )
    conn.commit()


def seed_domain(conn) -> None:
    domain = os.environ.get("MAILHUB_DOMAIN")
    if not domain or domain == "example.com":
        return
    inbound_host = os.environ.get("MAILHUB_INBOUND_HOST") or domain
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO domains (domain, inbound_host, receive_enabled, send_enabled)
            VALUES (%s,%s,true,true)
            ON CONFLICT (domain) DO NOTHING
            """,
            (domain, inbound_host),
        )
    conn.commit()


def ensure_dirs() -> None:
    for value in (
        os.environ.get("RAW_DIR", "/opt/mailhub/raw"),
        os.environ.get("LOG_DIR", "/opt/mailhub/logs"),
        os.environ.get("MAILHUB_UPLOAD_DIR", "/opt/mailhub/uploads/outbound"),
        os.environ.get("MAILHUB_OUTBOUND_DIR", "/opt/mailhub/raw/outbound"),
    ):
        Path(value).mkdir(parents=True, exist_ok=True)


def main() -> int:
    ensure_dirs()
    with connect_with_retry() as conn:
        apply_schema(conn)
        seed_admin(conn)
        seed_domain(conn)
        set_app_config(conn, "app_name", os.environ.get("MAILHUB_APP_NAME", "Mailhub"))
        set_app_config(conn, "public_base_url", os.environ.get("API_BASE_URL", "http://localhost:3024"))
        set_app_config(conn, "inbound_host", os.environ.get("MAILHUB_INBOUND_HOST") or os.environ.get("MAILHUB_DOMAIN") or "localhost")
        set_app_config(conn, "install_id", os.environ.get("MAILHUB_INSTALL_ID") or secrets.token_hex(8))
    print("mailhub bootstrap complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())

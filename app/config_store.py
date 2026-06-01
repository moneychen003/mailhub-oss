from __future__ import annotations

import os
from urllib.parse import urlparse

from . import db


DEFAULT_APP_NAME = "Mailhub"


def public_base_url() -> str:
    row = db.fetchone("SELECT value FROM app_config WHERE key='public_base_url'")
    if row and row.get("value"):
        return str(row["value"]).rstrip("/")
    return os.environ.get("API_BASE_URL", "http://localhost:3024").rstrip("/")


def public_host(default: str = "mail.example.com") -> str:
    parsed = urlparse(public_base_url())
    return parsed.hostname or default


def get_app_config() -> dict:
    rows = db.fetchall("SELECT key, value FROM app_config")
    cfg = {r["key"]: r["value"] for r in rows}
    return {
        "app_name": cfg.get("app_name") or DEFAULT_APP_NAME,
        "public_base_url": cfg.get("public_base_url") or os.environ.get("API_BASE_URL", "http://localhost:3024"),
        "inbound_host": cfg.get("inbound_host") or public_host(),
        "default_timezone": cfg.get("default_timezone") or os.environ.get("TZ", "UTC"),
    }


def set_app_config(values: dict[str, str | None]) -> None:
    for key, value in values.items():
        db.execute(
            """
            INSERT INTO app_config (key, value, updated_at)
            VALUES (%s, %s, now())
            ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()
            """,
            (key, value),
        )


def ensure_self_host_schema() -> None:
    """Apply additive schema changes needed by self-hosting settings.

    schema.sql is still the canonical fresh-install schema. This helper keeps
    existing deployments safe when the API starts before a manual migration.
    """
    with db.conn() as c, c.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS app_config (
              key TEXT PRIMARY KEY,
              value TEXT,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS smtp_config (
              id INT PRIMARY KEY DEFAULT 1,
              mode TEXT NOT NULL DEFAULT 'local_postfix',
              host TEXT,
              port INT NOT NULL DEFAULT 587,
              username TEXT,
              password TEXT,
              use_tls BOOLEAN NOT NULL DEFAULT false,
              use_starttls BOOLEAN NOT NULL DEFAULT true,
              enabled BOOLEAN NOT NULL DEFAULT true,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              CHECK (id = 1)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS imap_accounts (
              id BIGSERIAL PRIMARY KEY,
              label TEXT NOT NULL,
              host TEXT NOT NULL,
              port INT NOT NULL DEFAULT 993,
              username TEXT NOT NULL,
              password TEXT NOT NULL,
              mailbox TEXT NOT NULL DEFAULT 'INBOX',
              use_ssl BOOLEAN NOT NULL DEFAULT true,
              enabled BOOLEAN NOT NULL DEFAULT true,
              source TEXT,
              last_uid BIGINT,
              last_sync_at TIMESTAMPTZ,
              last_error TEXT,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_imap_accounts_enabled ON imap_accounts(enabled, updated_at DESC)")
        for column_sql in (
            "ALTER TABLE domains ADD COLUMN IF NOT EXISTS dkim_public_key TEXT",
            "ALTER TABLE domains ADD COLUMN IF NOT EXISTS inbound_host TEXT",
            "ALTER TABLE domains ADD COLUMN IF NOT EXISTS mx_status TEXT DEFAULT 'pending'",
            "ALTER TABLE domains ADD COLUMN IF NOT EXISTS spf_status TEXT DEFAULT 'pending'",
            "ALTER TABLE domains ADD COLUMN IF NOT EXISTS dmarc_status TEXT DEFAULT 'pending'",
            "ALTER TABLE domains ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ",
            "ALTER TABLE senders ADD COLUMN IF NOT EXISTS signature_text TEXT",
            "ALTER TABLE senders ADD COLUMN IF NOT EXISTS signature_html TEXT",
        ):
            cur.execute(column_sql)
        c.commit()

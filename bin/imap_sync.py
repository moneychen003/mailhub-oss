#!/usr/bin/env python3
"""Sync configured IMAP accounts into Mailhub.

This is intentionally boring: fetch by UID, hand raw RFC822 bytes to the same
ingest path used by Postfix, then advance last_uid only after successful DB
insert. It can run once from the settings page or in a loop/timer.
"""
from __future__ import annotations

import argparse
import imaplib
import importlib.util
import os
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import db
from app.config_store import ensure_self_host_schema

load_dotenv("/opt/mailhub/.env")
load_dotenv(ROOT / ".env")

spec = importlib.util.spec_from_file_location("mailhub_ingest", ROOT / "bin" / "ingest.py")
if not spec or not spec.loader:
    raise RuntimeError("Cannot load bin/ingest.py")
mailhub_ingest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mailhub_ingest)


def _connect(account: dict):
    if account.get("use_ssl"):
        return imaplib.IMAP4_SSL(account["host"], int(account["port"]), timeout=30)
    return imaplib.IMAP4(account["host"], int(account["port"]), timeout=30)


def _uid_list(imap, last_uid: int | None, limit: int) -> list[int]:
    criterion = f"UID {int(last_uid) + 1}:*" if last_uid else "ALL"
    typ, data = imap.uid("search", None, criterion)
    if typ != "OK":
        raise RuntimeError(f"IMAP UID search failed: {typ} {data!r}")
    ids = [int(x) for x in (data[0] or b"").split() if x]
    return ids[:limit]


def sync_account(account: dict, limit: int) -> dict:
    imported = 0
    highest_uid = int(account["last_uid"] or 0)
    with _connect(account) as imap:
        imap.login(account["username"], account["password"])
        typ, _ = imap.select(account.get("mailbox") or "INBOX", readonly=True)
        if typ != "OK":
            raise RuntimeError(f"Cannot select mailbox {account.get('mailbox') or 'INBOX'}")
        for uid in _uid_list(imap, highest_uid or None, limit):
            typ, data = imap.uid("fetch", str(uid), "(RFC822)")
            if typ != "OK" or not data:
                raise RuntimeError(f"IMAP fetch failed for UID {uid}: {typ}")
            raw = None
            for item in data:
                if isinstance(item, tuple) and item[1]:
                    raw = item[1]
                    break
            if not raw:
                continue
            mailhub_ingest.ingest(
                raw,
                envelope_sender="",
                envelope_recipient=account["username"],
                source=account.get("source") or account["label"],
            )
            imported += 1
            highest_uid = max(highest_uid, uid)
    db.execute(
        "UPDATE imap_accounts SET last_uid=%s, last_sync_at=now(), last_error=NULL WHERE id=%s",
        (highest_uid or None, account["id"]),
    )
    return {"id": account["id"], "label": account["label"], "imported": imported, "last_uid": highest_uid or None}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-id", type=int)
    parser.add_argument("--all", action="store_true", help="sync all enabled accounts")
    parser.add_argument("--limit", type=int, default=int(os.environ.get("MAILHUB_IMAP_SYNC_LIMIT", "50")))
    args = parser.parse_args()

    ensure_self_host_schema()
    if args.account_id:
        accounts = db.fetchall("SELECT * FROM imap_accounts WHERE id=%s", (args.account_id,))
    else:
        accounts = db.fetchall("SELECT * FROM imap_accounts WHERE enabled=true ORDER BY id")
    if not accounts:
        print("no imap accounts")
        return 0

    rc = 0
    for account in accounts:
        try:
            print(sync_account(account, args.limit))
        except Exception as e:
            rc = 1
            db.execute("UPDATE imap_accounts SET last_error=%s, last_sync_at=now() WHERE id=%s", (repr(e), account["id"]))
            print(f"imap sync failed for {account['label']}: {e!r}", file=sys.stderr)
            traceback.print_exc()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
